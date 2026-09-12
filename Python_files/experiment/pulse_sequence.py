"""
pulse_sequence.py -- base class for composable pulse sequences (py3 port).

Port of the lab's legacy `servers/pulser/pulse_sequences/pulse_sequence.py`. A
sequence subclass declares `required_parameters` and implements `sequence()`,
adding TTL (and DDS) pulses in real units; the parameter values arrive in a
TreeDict (loaded from the ParameterVault by the experiment). `programSequence()`
ships the pulses to the Pulser.

This is the framework the real experiment layer builds on: keep "what pulses, when"
in a sequence class (here / in `pulser_sequences/`), and let an experiment
(`experiment_scripts/`) load the parameters and run it.

py3 changes vs the legacy:
- uses our local `treedict` (script_scanner/treedict.py) instead of the py2 pkg;
- DDS is hardware-deferred, so `programSequence` sends TTL pulses and only attempts
  DDS if the sequence actually defines any (raising a clear message otherwise);
- `addTTL`/`addDDS` track the sequence end time (handy for the run timeout);
- `addSequence` now also merges the subsequence's TTL pulses (the legacy had that
  line commented out), so composition works for TTL too.
"""
import os
import sys

from labrad.units import WithUnit

# treedict lives in the script_scanner package; make it importable wherever this
# module is used (the ScriptScanner server already has both dirs on sys.path)
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # Python_files
for _p in (os.path.join(_ROOT, 'script_scanner'), _ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)
from treedict import TreeDict   # noqa: E402


class pulse_sequence(object):
    '''Base class for all pulse sequences.'''

    required_parameters = []
    required_subsequences = []
    replaced_parameters = {}

    def __init__(self, parameter_dict=None, start=None):
        if parameter_dict is None:
            parameter_dict = TreeDict()
        if start is None:
            start = WithUnit(0, 's')
        self.start = start
        self.end = start
        self._dds_pulses = []
        self._ttl_pulses = []
        self.replace = parameter_dict
        self.parameters = self.fill_parameters(self.required_parameters, self.replace)
        self.sequence()

    @classmethod
    def all_required_parameters(cls):
        '''All parameters required by this sequence and its subsequences.'''
        required = set(cls.required_parameters)
        for subsequence in cls.required_subsequences:
            replaced = set(cls.replaced_parameters.get(subsequence, []))
            additional = set(subsequence.all_required_parameters())
            additional.difference_update(replaced)
            required = required.union(additional)
        return list(required)

    def sequence(self):
        '''implemented by the subclass'''

    def fill_parameters(self, params, replace):
        if not len(params) == len(set(params)):
            raise Exception("Duplicate required parameters found in {0}".format(self.__class__.__name__))
        new_dict = TreeDict()
        for collection, parameter_name in params:
            key = '{0}.{1}'.format(collection, parameter_name)
            try:
                new_dict[key] = replace[key]
            except KeyError:
                raise Exception('{0} {1} value not provided for the {2} Pulse Sequence'.format(
                    collection, parameter_name, self.__class__.__name__))
        return new_dict

    def addTTL(self, channel, start, duration):
        '''add a TTL pulse (named channel; start/duration are labrad time Values).'''
        self._ttl_pulses.append((channel, start, duration))
        self.end = max(self.end, start + duration)

    def addDDS(self, channel, start, duration, frequency, amplitude,
               phase=None, ramp_rate=None, amp_ramp_rate=None):
        '''add a DDS pulse (stored; DDS is hardware-deferred -- see programSequence).'''
        if phase is None:
            phase = WithUnit(0, 'deg')
        if ramp_rate is None:
            ramp_rate = WithUnit(0, 'MHz')
        if amp_ramp_rate is None:
            amp_ramp_rate = WithUnit(0, 'dB')
        self._dds_pulses.append((channel, start, duration, frequency, amplitude, phase, ramp_rate, amp_ramp_rate))
        self.end = max(self.end, start + duration)

    def addSequence(self, sequence, replacement_dict=None, position=None):
        '''insert a subsequence at `position` (or at the current end).'''
        if replacement_dict is None:
            replacement_dict = TreeDict()
        if sequence not in self.required_subsequences:
            raise Exception("Adding subsequence {0} not listed in required_subsequences".format(sequence.__name__))
        if position is None:
            position = self.end
        replacement = TreeDict()
        replacement.update(self.replace)
        replacement.update(replacement_dict)
        seq = sequence(replacement, start=position)
        self._dds_pulses.extend(seq._dds_pulses)
        self._ttl_pulses.extend(seq._ttl_pulses)
        self.end = max(self.end, seq.end)

    def programSequence(self, pulser):
        '''compile + load this sequence into the Pulser.'''
        pulser.new_sequence()
        if self._ttl_pulses:
            pulser.add_ttl_pulses(self._ttl_pulses)
        if self._dds_pulses:
            try:
                pulser.add_dds_pulses(self._dds_pulses)
            except Exception:
                raise Exception("This sequence uses DDS pulses, but the Pulser has no DDS "
                                "support yet (DDS is hardware-deferred) -- use TTL-only sequences.")
        pulser.program_sequence()
