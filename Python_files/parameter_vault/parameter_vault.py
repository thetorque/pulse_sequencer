"""
### BEGIN NODE INFO
[info]
name = ParameterVault
version = 2.1
description = Central store of experiment parameters (py3, scalabrad)
instancename = ParameterVault

[startup]
cmdline = %PYTHON% %FILE%
timeout = 20

[shutdown]
message = 987654321
timeout = 20
### END NODE INFO
"""
# parameter_vault.py -- py3 port of the legacy servers/parameter_vault.
#
# A LabRAD server holding the experiment's parameters in memory, backed by the
# LabRAD Registry. Parameters are keyed by (collection, parameter_name) and
# carry a type tag that says how to interpret the stored value:
#
#   parameter            (min, max, current)         -> current, bounds-checked
#   duration_bandwidth   (min, max, current)         -> current, bounds-checked
#   scan                 ((min,max), (start,stop,N))  -> (start, stop, N), checked
#   selection_simple     (choice, [choices])          -> choice
#   line_selection       (choice, [(label,val),...])  -> choice
#   string / bool / sideband_selection / spectrum_sensitivity -> value as-is
#
# Same LabRAD name, setting IDs/names, and parameter-change signal as the legacy
# server, so existing clients and experiment scripts work unchanged. Ported off
# py2 (.iteritems, a debug print, tuple-key details) and hardened so a fresh
# scalabrad registry (empty 'Parameter Vault' tree) doesn't crash startup.
from labrad.server import LabradServer, setting, Signal
from twisted.internet.defer import inlineCallbacks, returnValue


class ParameterVault(LabradServer):
    """Data server for storing ongoing experimental parameters."""

    name = "ParameterVault"
    registryDirectory = ['', 'Servers', 'Parameter Vault']
    onParameterChange = Signal(612512, 'signal: parameter change', '(ss)')

    @inlineCallbacks
    def initServer(self):
        self.listeners = set()
        self.parameters = {}
        yield self.load_parameters()

    def initContext(self, c):
        """Initialize a new context object."""
        self.listeners.add(c.ID)

    def expireContext(self, c):
        self.listeners.discard(c.ID)

    def getOtherListeners(self, c):
        notified = self.listeners.copy()
        notified.discard(c.ID)
        return notified

    # ---- registry <-> memory ----------------------------------------------
    @inlineCallbacks
    def load_parameters(self):
        """(Re)load every parameter from the registry into memory."""
        self.parameters = {}
        # ensure the base directory exists so a fresh registry doesn't crash
        yield self.client.registry.cd(self.registryDirectory, True)
        yield self._addParametersInDirectory(self.registryDirectory, [])

    @inlineCallbacks
    def _addParametersInDirectory(self, topPath, subPath):
        yield self.client.registry.cd(topPath + subPath)
        directories, parameters = yield self.client.registry.dir()
        if subPath:  # ignore parameters in the top level
            for parameter in parameters:
                value = yield self.client.registry.get(parameter)
                key = tuple(subPath + [parameter])
                self.parameters[key] = value
        for directory in directories:
            newpath = subPath + [directory]
            yield self._addParametersInDirectory(topPath, newpath)

    @inlineCallbacks
    def save_parameters(self):
        """Save the in-memory parameters back into the registry."""
        regDir = self.registryDirectory
        for key, value in self.parameters.items():
            key = list(key)
            parameter_name = key.pop()
            fullDir = regDir + key
            yield self.client.registry.cd(fullDir, True)
            yield self.client.registry.set(parameter_name, value)

    # ---- value helpers -----------------------------------------------------
    def _get_parameter_names(self, collection):
        return [key[1] for key in self.parameters.keys() if key[0] == collection]

    def _get_collections(self):
        return list({key[0] for key in self.parameters.keys()})

    def _save_full(self, key, value):
        t, item = self.parameters[key]
        if t == 'parameter':
            assert item[0] <= value <= item[1], "Parameter {} Out of Bound".format(key[1])
            item[2] = value
            return (t, item)
        else:
            raise Exception("Can't save, not one of checkable types")

    def check_parameter(self, name, value):
        """Reduce a stored (type, item) value to its effective value."""
        t, item = value
        if t == 'parameter' or t == 'duration_bandwidth':
            assert item[0] <= item[2] <= item[1], "Parameter {} Out of Bound".format(name)
            return item[2]
        elif t in ('string', 'bool', 'sideband_selection', 'spectrum_sensitivity'):
            return item
        elif t == 'scan':
            minim, maxim = item[0]
            start, stop, steps = item[1]
            assert minim <= start <= maxim, "Parameter {} Out of Bound".format(name)
            assert minim <= stop <= maxim, "Parameter {} Out of Bound".format(name)
            return (start, stop, steps)
        elif t == 'selection_simple':
            assert item[0] in item[1], "Incorrect selection made in {}".format(name)
            return item[0]
        elif t == 'line_selection':
            assert item[0] in dict(item[1]).keys(), "Incorrect selection made in {}".format(name)
            return item[0]
        else:  # parameter type not known -- hand it back untouched
            return value

    # ---- settings ----------------------------------------------------------
    @setting(0, "Set Parameter", collection='s', parameter_name='s', value='?', full_info='b', returns='')
    def setParameter(self, c, collection, parameter_name, value, full_info=False):
        """Set a parameter's value (full_info replaces the whole typed record)."""
        key = (collection, parameter_name)
        if key not in self.parameters.keys():
            raise Exception("Parameter Not Found")
        if full_info:
            self.parameters[key] = value
        else:
            self.parameters[key] = self._save_full(key, value)
        notified = self.getOtherListeners(c)
        self.onParameterChange((key[0], key[1]), notified)

    @setting(1, "Get Parameter", collection='s', parameter_name='s', checked='b', returns=['?'])
    def getParameter(self, c, collection, parameter_name, checked=True):
        """Get a parameter's value (checked reduces it to its effective value)."""
        key = (collection, parameter_name)
        if key not in self.parameters.keys():
            raise Exception("Parameter Not Found")
        result = self.parameters[key]
        if checked:
            result = self.check_parameter(key, result)
        return result

    @setting(2, "Get Parameter Names", collection='s', returns='*s')
    def getParameterNames(self, c, collection):
        """All parameter names in a collection."""
        return self._get_parameter_names(collection)

    @setting(3, "Save Parameters To Registry", returns='')
    def saveParametersToRegistry(self, c):
        """Persist the current parameters into the registry."""
        yield self.save_parameters()

    @setting(4, "Get Collections", returns='*s')
    def get_collection_names(self, c):
        """All collection names."""
        return self._get_collections()

    @setting(5, "Refresh Parameters", returns='')
    def refresh_parameters(self, c):
        """Save parameters to the registry, then reload them."""
        yield self.save_parameters()
        yield self.load_parameters()

    @setting(6, "Reload Parameters", returns='')
    def reload_parameters(self, c):
        """Discard the in-memory parameters and reload from the registry."""
        yield self.load_parameters()

    @inlineCallbacks
    def stopServer(self):
        try:
            yield self.save_parameters()
        except AttributeError:
            # values don't exist yet (e.g. stopServer after an identification error)
            pass


if __name__ == "__main__":
    from labrad import util
    util.runServer(ParameterVault())
