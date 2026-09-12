"""
configuration.py -- which experiment classes ScriptScanner offers, and their
concurrency rules (py3 port).

`scripts` is a list of (import_path, class_name). The server imports each and
registers the class under its `.name`. The import path is a normal module path;
because the server runs from this directory, the bundled `sample_experiment`
module is importable directly. Point new entries at your own experiment modules
as you port the experiment layer (experiment_scripts / pulser_sequences).

`allowed_concurrent` maps an experiment name to the list of experiments allowed
to run at the same time; anything not listed conflicts (and a higher-priority
scan will pause it). Empty by default -- everything is mutually exclusive.
"""


class config(object):

    # list in the format (import_path, class_name)
    scripts = [
        ('sample_experiment', 'sleep_experiment'),
        ('sample_experiment', 'pmt_point'),
        ('sample_experiment', 'led_staircase'),
        ('sample_experiment', 'led_blink'),
        ('sample_experiment', 'crashing_example'),
    ]

    allowed_concurrent = {
    }

    launch_history = 1000
