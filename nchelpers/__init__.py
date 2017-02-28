import hashlib
import re

from netCDF4 import Dataset, num2date
import numpy as np
from nchelpers.util import resolution_standard_name, time_to_seconds


class CFDataset(Dataset):
    """Represents a CF (climate and forecast) dataset stored in a NetCDF file.
    Methods on this class expose metadata that is expected to be found in such files,
    and values computed from that metadata.

    / == done
    /get_file_metadata
        - convert to properties that alias actual nc file attributes
        - don't include time metadata; provide direct properties on CFDataset instead
    /create_unique_id

    /nc_get_dim_axes_from_names
    /nc_get_dim_names
    /nc_get_dim_axes
    /get_climatology_bounds_var_name
    /is_multi_year_mean
    /get_time_step_size
    /get_time_resolution
    /get_timeseries -> time_steps
    /get_time_range
    /get_first_MiB_md5sum
    /get_important_varnames
    """
    # TODO: Improve this lame documentation ^^

    def __init__(self, *args, **kwargs):
        # super(netCDF4.Dataset, self).__init__(*args, **kwargs)  # Python 2. Uh-oh, doesn't work in 3
        super().__init__(*args, **kwargs)

    @property
    def first_MiB_md5sum(self):
        """MD5 digest of first MiB of this file"""
        m = hashlib.md5()
        with open(self.filepath(), 'rb') as f:
            m.update(f.read(2**20))
        return m.digest()

    @property
    def important_varnames(self):
        """A list of the primary (dependent) variables in this file.

        Many variables in a NetCDF file describe the *structure* of the data and aren't necessarily the
        values that we actually care about. For example a file with temperature data also has to include
        latitude/longitude variables, a time variable, and possibly bounds variables for each of the dimensions.
        These dimensions and bounds are independent variables.

        This function filters out the names of all independent variables and just gives you the "important" (dependent)
        variable names.
        """
        variables = set(self.variables.keys())
        dimensions = set(self.dimensions.keys())
        return [v for v in variables - dimensions if 'bnds' not in v]
    # Define an alias with a more explantory name
    dependent_varnames = important_varnames

    def dim_names(self, var_name=None):
        """Return names of dimensions of a specified variable (or all dimensions) in this file
        
        :param var_name: (str) Name of variable of interest (or None for all dimensions)
        :return (tuple): A tuple containing the names of the dimensions of the specified variable or of
            all dimensions in the file
        """
        if var_name:
            return self.variables[var_name].dimensions
        else:
            return tuple(k for k in self.dimensions.keys())

    def dim_axes_from_names(self, dim_names=None):
        """Translate well-known dimension names to canonical axis names.
        Canonical axis names are 'X', 'Y', 'Z', 'T'.
        See dict dim_to_axis for dimension names recognized.
        
        :param dim_names: (list of str) List of names of dimensions of interest, None for all dimensions in file
        :return: (dict) Dictionary mapping canonical axis name back to dimension name, for specified dimension names
        """
        if not dim_names:
            dim_names = self.dim_names()
        dim_to_axis = {
            'lat': 'Y',
            'latitude': 'Y',
            'lon': 'X',
            'longitude': 'X',
            'xc': 'X',
            'yc': 'Y',
            'x': 'X',
            'y': 'Y',
            'time': 'T',
            'timeofyear': 'T',
            'plev': 'Z',
            'lev': 'Z',
            'level': 'Z'
        }
        return {dim_to_axis[dim]: dim for dim in dim_names if dim in dim_to_axis}

    def dim_axes(self, dim_names=None):
        """Return a dictionary mapping specified dimension names (or all dimensions in file) to
        the canonical axis name for each dimension.
        
        :param dim_names: (str) List of names of dimensions of interest, None for all dimensions in file
        :return: (dict) Dictionary mapping dimension name to canonical axis name, for specified dimension names
        """
        # TODO: Remove debugging print statements
        if not dim_names:
            dim_names = self.dim_names()

        if len(dim_names) == 0:
            return {}

        print('\ndim_axes(', dim_names, ')')

        # Start with our best guess
        axis_to_dim = self.dim_axes_from_names(dim_names)
        print('axis_to_dim = ', axis_to_dim)

        # Then fill in the rest from the 'axis' attributes
        # TODO: Does this happen? i.e., when are dimension names the same as axis names?
        # Alternatively, is this some kind of (relatively benign) programming error?
        for axis in axis_to_dim.keys():
            print(axis)
            if axis in self.dimensions and axis in self.variables \
                    and hasattr(self.variables[axis], 'axis'):
                print('extra')
                axis_to_dim[axis] = self.variables[axis].axis

                # Apparently this is how a "space" dimension is attributed?
                if hasattr(self.variables[axis], 'compress'):
                    axis_to_dim[axis] = 'S'

        # Invert {axis: dim} to {dim: axis}
        return {dim: axis for axis, dim in axis_to_dim.items()}

    @property
    def climatology_bounds_var_name(self):
        axes = self.dim_axes()
        if 'T' in axes:
            time_axis = axes['T']
        else:
            return None

        # TODO: Do we really mean 'climatology' in self.variables[time_axis].ncattrs()? If so, use that. This looks
        # imprecise and hard to understand
        if 'climatology' in self.variables[time_axis]:
            return self.variables[time_axis].climatology
        else:
            return None

    @property
    def is_multi_year_mean(self):
        """True if the metadata indicates that the data consists of a multi-year mean"""
        # TODO: Is it really true that every data file that consists of a multi-year mean actually (should) contain a
        # time dimension with attribute 'climatology'? Or is there a better condition, perhaps based on cell_method?
        return bool(self.climatology_bounds_var_name)

    @property
    def time_steps(self):
        """List of timesteps, i.e., values of the time dimension, in this file"""
        axes = self.dim_axes_from_names()
        if 'T' in axes:
            time_axis = axes['T']
        else:
            raise ValueError("No axis is attributed with time information")

        t = self.variables[time_axis]

        assert hasattr(t, 'units') and hasattr(t, 'calendar')

        return {
            'units': t.units,
            'calendar': t.calendar,
            'numeric': t[:],
            'datetime': num2date(t[:], t.units, t.calendar)
        }

    # TODO: Is this property useful anywhere except in time_range_formatted?
    @property
    def time_range(self):
        t = self.time_steps['numeric']
        return np.min(t), np.max(t)

    @property
    def time_range_formatted(self):
        format = {'yearly': '%Y', 'monthly': '%Y%m', 'daily': '%Y%m%d'}.get(self.time_resolution, None)
        if not format:
            raise ValueError("Cannot format a time range with resolution '{}' (only yearly, monthly or daily)"
                             .format(self.time_resolution))
        t_min, t_max = num2date(self.time_range, self.time_steps['units'], self.time_steps['calendar'])
        print(t_min, t_max)
        return '{}-{}'.format(t_min.strftime(format), t_max.strftime(format))

    @property
    def time_step_size(self):
        time_steps = self.time_steps
        match = re.match('(days|hours|minutes|seconds) since.*', time_steps['units'])
        if match:
            scale = match.groups()[0]
        else:
            raise ValueError("cf_units param must be a string of the form '<time units> since <reference time>'")
        med = np.median(np.diff(time_steps['numeric']))
        return time_to_seconds(med, scale)

    @property
    def time_resolution(self):
        """Returns a standard string that describes the time resolution of the file"""
        #if self.is_multi_year_mean:
        #    return 'other'
        return resolution_standard_name(self.time_step_size)

    # TODO: Remove when all the juice has been squeezed
    # def _get_file_metadata(nc, map_):
    #     missing = []
    #     required = map_.keys()
    #     for key in required:
    #         if not hasattr(nc, key):
    #             missing.append(key)
    #     if missing:
    #         raise ValueError(required_nc_attributes_msg.format(required, nc.filepath(), missing))
    #
    #     return {
    #         to_: getattr(nc, from_)
    #         for from_, to_ in map_.items()
    #         }
    #
    # def file_metadata(nc):
    #     """Return important global attributes from this file"""
    #     if self.project_id == 'CMIP5':
    #         meta = _get_file_metadata(nc, global_to_res_map_cmip5)
    #     else:
    #         meta = _get_file_metadata(nc, global_to_res_map_cmip3)
    #
    #     # Which variable(s) does this file contain?
    #     meta['var'] = '+'.join(get_important_varnames(nc))  # just do the computation where needed
    #
    #     # Compute time metadata from the time value
    #     time = get_timeseries(nc)
    #     meta['tres'] = get_time_resolution(time['numeric'], time['units'])  # == self.time_resolution
    #     tmin, tmax = get_time_range(nc)
    #     tmin, tmax = num2date([tmin, tmax], time['units'], time['calendar'])
    #     meta['trange'] = format_time_range(tmin, tmax, meta['tres'])  # == self.time_range_formatted
    #
    #     return meta

    class UnifiedMetadata(object):
        """Presents a unified interface to certain global metadata attributes in a CFDataset object.
        Why?
        - A CFDataset can have metadata attributes named according to CMIP3 or CMIP5 standards, depending on the file's
          origin (which is indicated by project_id).
        - We want a common interface, i.e., common names, for a selected set of those differently named attributes.
        - We must avoid shadowing existing properties and methods on a CFDataset (or really, a netCDF4.Dataset) object
          with the unified names we'd like to use for these metadata properties.
        - We'd like to present them as properties instead of as a dict, which has uglier syntax
        How?
        - Create a property called metadata on CFDataset that is an instance of this class.
        """
        # TODO: Make this a singleton

        def __init__(self, dataset):
            self.dataset = dataset

        _aliases = {
            'institution': {
                'CMIP3': 'institute',
                'CMIP5': 'institute_id',
            },
            'model': {
                'CMIP3': 'source',
                'CMIP5': 'model_id',
            },
            'emissions': {
                'CMIP3': 'experiment_id',
                'CMIP5': 'experiment_id',
            },
            'run': {
                'CMIP3': 'realization',
                'CMIP5': 'parent_experiment_rip',
            },
            'project': {
                'CMIP3': 'project_id',
                'CMIP5': 'project_id',
            },
        }

        def __getattr__(self, item):
            # TODO: Do we want more explict exceptions like the one in _get_file_metadata?
            # There are 3 errors here that get munged into one exception
            try:
                return getattr(self.dataset, self._aliases[item][self.dataset.project_id])
            except:
                raise AttributeError

    @property
    def metadata(self):
        return self.UnifiedMetadata(self)

    @property
    def unique_id(self):
        """A metadata-based unique id for this file"""
        dim_axes = set(self.dim_axes_from_names().keys())
        if dim_axes <= {'X', 'Y', 'Z', 'T'}:
            axes = ''
        else:
            axes = "_dim" + ''.join(sorted(dim_axes))
        return '{vars}_{tres}_{model}_{emissions}_{run}_{trange}{axes}'.format(
            vars='-'.join(self.dependent_varnames),
            tres=self.time_resolution,
            model=self.metadata.model,
            emissions=self.metadata.emissions,
            run=self.metadata.run,
            trange=self.time_range_formatted,
            axes=axes,
        )\
            .replace('+', '-')