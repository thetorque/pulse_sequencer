"""
scan_methods.py -- experiment base class + launch wrappers (py3 port).

`experiment` is the base every experiment script subclasses; it connects to
LabRAD in its worker thread, loads its required parameters from the
ParameterVault into a TreeDict, and drives the initialize/run/finalize lifecycle
while reporting progress and honouring pause/stop through the ScriptScanner
server.

The wrappers turn one experiment class into a queued scan:
  - single                    : run once
  - repeat_reload             : run N times, reloading parameters each time
  - scan_experiment_1D        : sweep one parameter, saving result vs value
  - scan_experiment_1D_measure: sweep one experiment while measuring another

py3 changes: print()-functions; .iteritems() -> .items(); the local py3
`treedict` (this package) instead of the py2 `treedict` package; ParameterVault
is now OPTIONAL -- an experiment with no required parameters runs without it, so
the stack is testable before every server is up.
"""
import traceback
from time import localtime, strftime

from numpy import linspace
import labrad
from labrad.units import WithUnit

from treedict import TreeDict


class experiment_info(object):
    '''
    holds information about the experiment
    '''
    required_parameters = []
    name = ''

    def __init__(self, name=None, required_parameters=None):
        if name is not None:
            self.name = name
        if required_parameters is not None:
            self.required_parameters = required_parameters
        self.parameters = TreeDict()


class experiment(experiment_info):

    def __init__(self, name=None, required_parameters=None, cxn=None,
                 min_progress=0.0, max_progress=100.0):
        required_parameters = self.all_required_parameters()
        super(experiment, self).__init__(name, required_parameters)
        self.cxn = cxn
        self.pv = None
        self.sc = None
        self.context = None
        self.min_progress = min_progress
        self.max_progress = max_progress
        self.should_stop = False

    def _connect(self):
        if self.cxn is None:
            try:
                self.cxn = labrad.connect()
            except Exception:
                raise Exception("Not able to connect to LabRAD")
        try:
            self._define_servers(self.cxn)
        except Exception:
            raise Exception("ScriptScanner is not running")

    def _define_servers(self, cxn):
        self.sc = cxn.servers['ScriptScanner']
        # ParameterVault is optional: an experiment with no required parameters
        # can run without it, which keeps the stack testable incrementally.
        try:
            self.pv = cxn.servers['ParameterVault']
        except Exception:
            self.pv = None
        self.context = cxn.context()

    def execute(self, ident):
        '''
        executes the experiment
        '''
        self.ident = ident
        try:
            self._connect()
            self._initialize(self.cxn, self.context, ident)
            self._run(self.cxn, self.context)
            self._finalize(self.cxn, self.context)
        except Exception:
            reason = traceback.format_exc()
            print(reason)
            if getattr(self, 'sc', None) is not None:
                self.sc.error_finish_confirmed(self.ident, reason)
        finally:
            if getattr(self, 'cxn', None) is not None:
                self.cxn.disconnect()
                self.cxn = None

    def _initialize(self, cxn, context, ident):
        self._load_required_parameters()
        self.initialize(cxn, context, ident)
        self.sc.launch_confirmed(ident)

    def _run(self, cxn, context):
        self.run(cxn, context)

    def _load_required_parameters(self, overwrite=False):
        d = self._load_parameters_dict(self.required_parameters)
        self.parameters.update(d, overwrite=overwrite)

    def _load_parameters_dict(self, params):
        '''loads the required parameters into a treedict'''
        d = TreeDict()
        if params and self.pv is None:
            raise Exception("In {}: required parameters need the ParameterVault, "
                            "but it is not running".format(self.name))
        for collection, parameter_name in params:
            try:
                value = self.pv.get_parameter(collection, parameter_name)
            except Exception as e:
                print(e)
                raise Exception("In {}: Parameter {} not found among Parameter Vault "
                                "parameters".format(self.name, (collection, parameter_name)))
            else:
                d['{0}.{1}'.format(collection, parameter_name)] = value
        return d

    def set_parameters(self, parameter_dict):
        '''
        can reload all parameter values from parameter_vault or replace parameters
        with values from the provided parameter_dict
        '''
        if isinstance(parameter_dict, TreeDict):
            update_dict = parameter_dict
        elif isinstance(parameter_dict, dict):
            update_dict = TreeDict()
            for (collection, parameter_name), value in parameter_dict.items():
                update_dict['{0}.{1}'.format(collection, parameter_name)] = value
        else:
            raise Exception("Incorrect input type for the replacement dictionary")
        self.parameters.update(update_dict)

    def reload_some_parameters(self, params):
        d = self._load_parameters_dict(params)
        self.parameters.update(d)

    def reload_all_parameters(self):
        self._load_required_parameters(overwrite=True)

    def _finalize(self, cxn, context):
        self.finalize(cxn, context)
        self.sc.finish_confirmed(self.ident)

    # useful functions to be used in subclasses
    @classmethod
    def all_required_parameters(cls):
        return []

    def pause_or_stop(self):
        '''
        allows to pause and to stop the experiment
        '''
        self.should_stop = self.sc.pause_or_stop(self.ident)
        if self.should_stop:
            self.sc.stop_confirmed(self.ident)
        return self.should_stop

    def make_experiment(self, subexprt_cls):
        subexprt = subexprt_cls(cxn=self.cxn)
        subexprt._connect()
        subexprt._load_required_parameters()
        return subexprt

    def set_progress_limits(self, min_progress, max_progress):
        self.min_progress = min_progress
        self.max_progress = max_progress

    # functions to reimplement in the subclass
    def initialize(self, cxn, context, ident):
        '''implemented by the subclass'''

    def run(self, cxn, context, replacement_parameters={}):
        '''implemented by the subclass'''

    def finalize(self, cxn, context):
        '''implemented by the subclass'''


class single(experiment):
    '''
    runs a single experiment
    '''
    def __init__(self, script_cls):
        self.script_cls = script_cls
        super(single, self).__init__(self.script_cls.name)

    def initialize(self, cxn, context, ident):
        self.script = self.make_experiment(self.script_cls)
        self.script.initialize(cxn, context, ident)

    def run(self, cxn, context, replacement_parameters={}):
        self.script.run(cxn, context)

    def finalize(self, cxn, context):
        self.script.finalize(cxn, context)


class repeat_reload(experiment):
    '''
    Used to repeat an experiment multiple times, reloading the parameters every repetition
    '''
    def __init__(self, script_cls, repetitions, save_data=False):
        self.script_cls = script_cls
        self.repetitions = repetitions
        self.save_data = save_data
        scan_name = self.name_format(script_cls.name)
        super(repeat_reload, self).__init__(scan_name)

    def name_format(self, name):
        return 'Repeat {0} {1} times'.format(name, self.repetitions)

    def initialize(self, cxn, context, ident):
        self.script = self.make_experiment(self.script_cls)
        self.script.initialize(cxn, context, ident)
        if self.save_data:
            self.navigate_data_vault(cxn, context)

    def run(self, cxn, context):
        for i in range(self.repetitions):
            if self.pause_or_stop():
                return
            self.script.reload_all_parameters()
            self.script.set_progress_limits(100.0 * i / self.repetitions,
                                             100.0 * (i + 1) / self.repetitions)
            result = self.script.run(cxn, context)
            if self.script.should_stop:
                return
            if self.save_data and result is not None:
                cxn.data_vault.add([i, result], context=context)
            self.update_progress(i)

    def navigate_data_vault(self, cxn, context):
        dv = cxn.data_vault
        local_time = localtime()
        dataset_name = self.name + strftime("%Y%b%d_%H%M_%S", local_time)
        directory = ['', 'ScriptScanner']
        directory.extend([strftime("%Y%b%d", local_time), strftime("%H%M_%S", local_time)])
        dv.cd(directory, True, context=context)
        dv.new(dataset_name, [('Iteration', 'Arb')], [(self.script.name, 'Arb', 'Arb')], context=context)
        dv.add_parameter('plotLive', True, context=context)

    def update_progress(self, iteration):
        progress = self.min_progress + (self.max_progress - self.min_progress) * \
            float(iteration + 1.0) / self.repetitions
        self.sc.script_set_progress(self.ident, progress)

    def finalize(self, cxn, context):
        self.script.finalize(cxn, context)


class scan_experiment_1D(experiment):
    '''
    Used to scan a single parameter of an experiment
    '''
    def __init__(self, script_cls, parameter, minim, maxim, steps, units):
        self.script_cls = script_cls
        self.parameter = parameter
        self.units = units
        # minim/maxim arrive as dimensionless labrad Values (tag 'v[]'); coerce to float
        self.scan_points = linspace(float(minim), float(maxim), steps)
        self.scan_points = [WithUnit(float(pt), units) for pt in self.scan_points]
        scan_name = self.name_format(script_cls.name)
        super(scan_experiment_1D, self).__init__(scan_name)

    def name_format(self, name):
        return 'Scanning {0} in {1}'.format(self.parameter, name)

    def initialize(self, cxn, context, ident):
        self.script = self.make_experiment(self.script_cls)
        self.script.initialize(cxn, context, ident)
        self.navigate_data_vault(cxn, context)

    def run(self, cxn, context):
        for i, scan_value in enumerate(self.scan_points):
            if self.pause_or_stop():
                return
            self.script.set_parameters({self.parameter: scan_value})
            self.script.set_progress_limits(100.0 * i / len(self.scan_points),
                                            100.0 * (i + 1) / len(self.scan_points))
            result = self.script.run(cxn, context)
            if self.script.should_stop:
                return
            if result is not None:
                if isinstance(result, tuple):  # add functionality if a tuple is returned from run
                    cxn.data_vault.add([scan_value[self.units], result[0]], context=context)
                else:
                    cxn.data_vault.add([scan_value[self.units], result], context=context)
            self.update_progress(i)

    def navigate_data_vault(self, cxn, context):
        dv = cxn.data_vault
        local_time = localtime()
        dataset_name = self.name + strftime("%Y%b%d_%H%M_%S", local_time)
        directory = ['', 'ScriptScanner']
        directory.extend([strftime("%Y%b%d", local_time), strftime("%H%M_%S", local_time) + self.name])
        dv.cd(directory, True, context=context)
        dv.new(dataset_name, [('Iteration', 'Arb')], [(self.script.name, 'Arb', 'Arb')], context=context)
        dv.add_parameter('plotLive', True, context=context)

    def update_progress(self, iteration):
        progress = self.min_progress + (self.max_progress - self.min_progress) * \
            float(iteration + 1.0) / len(self.scan_points)
        self.sc.script_set_progress(self.ident, progress)

    def finalize(self, cxn, context):
        self.script.finalize(cxn, context)


class scan_experiment_1D_measure(experiment):
    '''
    Scan a parameter of one experiment while measuring with another
    '''
    def __init__(self, scan_script_cls, measure_script_cls, parameter, minim, maxim, steps, units):
        self.scan_script_cls = scan_script_cls
        self.measure_script_cls = measure_script_cls
        self.parameter = parameter
        self.units = units
        # minim/maxim arrive as dimensionless labrad Values (tag 'v[]'); coerce to float
        self.scan_points = linspace(float(minim), float(maxim), steps)
        self.scan_points = [WithUnit(float(pt), units) for pt in self.scan_points]
        scan_name = self.name_format(scan_script_cls.name, measure_script_cls.name)
        super(scan_experiment_1D_measure, self).__init__(scan_name)

    def name_format(self, scan_name, measure_name):
        return 'Scanning {0} in {1} while measuring {2}'.format(self.parameter, scan_name, measure_name)

    def initialize(self, cxn, context, ident):
        self.scan_script = self.make_experiment(self.scan_script_cls)
        self.measure_script = self.make_experiment(self.measure_script_cls)
        self.scan_script.initialize(cxn, context, ident)
        self.measure_script.initialize(cxn, context, ident)
        self.navigate_data_vault(cxn, context)

    def run(self, cxn, context):
        for i, scan_value in enumerate(self.scan_points):
            if self.pause_or_stop():
                return
            self.scan_script.set_parameters({self.parameter: scan_value})
            self.scan_script.set_progress_limits(100.0 * i / len(self.scan_points),
                                                 100.0 * (i + 0.5) / len(self.scan_points))
            self.scan_script.run(cxn, context)
            if self.scan_script.should_stop:
                return
            self.measure_script.set_progress_limits(100.0 * (i + 0.5) / len(self.scan_points),
                                                    100.0 * (i + 1) / len(self.scan_points))
            result = self.measure_script.run(cxn, context)
            if self.measure_script.should_stop:
                return
            if result is not None:
                cxn.data_vault.add([scan_value[self.units], result], context=context)
            self.update_progress(i)

    def navigate_data_vault(self, cxn, context):
        dv = cxn.data_vault
        local_time = localtime()
        dataset_name = self.name + strftime("%Y%b%d_%H%M_%S", local_time)
        directory = ['', 'ScriptScanner']
        directory.extend([strftime("%Y%b%d", local_time), strftime("%H%M_%S", local_time)])
        dv.cd(directory, True, context=context)
        dv.new(dataset_name, [('Iteration', 'Arb')], [(self.measure_script.name, 'Arb', 'Arb')], context=context)
        dv.add_parameter('plotLive', True, context=context)

    def update_progress(self, iteration):
        progress = self.min_progress + (self.max_progress - self.min_progress) * \
            float(iteration + 1.0) / len(self.scan_points)
        self.sc.script_set_progress(self.ident, progress)

    def finalize(self, cxn, context):
        self.scan_script.finalize(cxn, context)
        self.measure_script.finalize(cxn, context)
