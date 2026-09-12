"""
treedict.py -- a tiny py3 stand-in for the legacy py2 `treedict` package.

The legacy experiment layer (scan_methods + every experiment script) stored an
experiment's parameters in a `TreeDict`: a nested dict that supports BOTH

    d['Collection.parameter_name'] = value      # dotted-string key
    d.Collection.parameter_name                 # dotted attribute access

The real `treedict` PyPI package is Python-2 only (C-extension, last released
2013) and never ported, so we implement just the subset the stack actually uses:
construction, dotted get/set (string key or attribute), and a recursive
`update(other, overwrite=...)`.

Semantics that scan_methods relies on:
- `update(d, overwrite=False)` keeps values that already exist (a first load has
  nothing to clobber); `reload_all_parameters` passes `overwrite=True` to refresh
  every value from the ParameterVault.
- Reading an absent branch raises AttributeError / KeyError, same as a dict.

This is intentionally small; it is not a drop-in for every treedict feature, only
for how the ion-clock experiment code uses it.
"""


class TreeDict(dict):
    """A dict whose keys may be dotted paths, with attribute access to branches."""

    # ---- dotted-string item access -------------------------------------
    def __getitem__(self, key):
        if isinstance(key, str) and '.' in key:
            head, rest = key.split('.', 1)
            branch = dict.__getitem__(self, head)
            return branch[rest]
        return dict.__getitem__(self, key)

    def __setitem__(self, key, value):
        if isinstance(key, str) and '.' in key:
            head, rest = key.split('.', 1)
            branch = self.get(head)
            if not isinstance(branch, TreeDict):
                branch = TreeDict()
                dict.__setitem__(self, head, branch)
            branch[rest] = value
        else:
            dict.__setitem__(self, key, value)

    def __contains__(self, key):
        if isinstance(key, str) and '.' in key:
            head, rest = key.split('.', 1)
            branch = self.get(head)
            return isinstance(branch, TreeDict) and rest in branch
        return dict.__contains__(self, key)

    def get(self, key, default=None):
        try:
            return self[key]
        except (KeyError, TypeError):
            return default

    # ---- attribute access to branches / leaves -------------------------
    def __getattr__(self, name):
        # only called when normal attribute lookup fails
        try:
            return dict.__getitem__(self, name)
        except KeyError:
            raise AttributeError(name)

    def __setattr__(self, name, value):
        dict.__setitem__(self, name, value)

    # ---- recursive merge ----------------------------------------------
    def update(self, other=None, overwrite=True, **kwargs):
        """Merge `other` (dict/TreeDict) into self, recursively.

        With overwrite=False, existing leaf values are preserved; branches are
        still merged so new keys are added.
        """
        if other:
            for key, value in dict(other).items():
                self._merge_one(key, value, overwrite)
        for key, value in kwargs.items():
            self._merge_one(key, value, overwrite)

    def _merge_one(self, key, value, overwrite):
        # dotted string key: descend/create the branch, then merge the leaf/branch
        if isinstance(key, str) and '.' in key:
            head, rest = key.split('.', 1)
            branch = dict.get(self, head)
            if not isinstance(branch, TreeDict):
                branch = TreeDict()
                dict.__setitem__(self, head, branch)
            branch._merge_one(rest, value, overwrite)
            return
        existing = dict.get(self, key)
        if isinstance(value, dict):
            if not isinstance(existing, TreeDict):
                existing = TreeDict()
                dict.__setitem__(self, key, existing)
            existing.update(value, overwrite=overwrite)
        else:
            if overwrite or key not in self:
                dict.__setitem__(self, key, value)

    def __repr__(self):
        return 'TreeDict(%s)' % dict.__repr__(self)
