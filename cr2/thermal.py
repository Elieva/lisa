#!/usr/bin/python
"""Process the output of the power allocator trace in the current
directory's trace.dat"""

import os
import re
from StringIO import StringIO
import pandas as pd
from matplotlib import pyplot as plt

from plot_utils import normalize_title, pre_plot_setup, post_plot_setup, plot_hist

def trace_parser_explode_array(string, array_lengths):
    """Explode an array in the trace into individual elements for easy parsing

    Basically, turn "load={1 1 2 2}" into "load0=1 load1=1 load2=2
    load3=2".  array_lengths is a dictionary of array names and their
    expected length.  If we get array that's shorter than the expected
    length, additional keys have to be introduced with value 0 to
    compensate.  For example, "load={1 2}" with array_lengths being
    {"load": 4} returns "load0=1 load1=2 load2=0 load3=0"

    """

    while True:
        match = re.search(r"[^ ]+={[^}]+}", string)
        if match is None:
            break

        to_explode = match.group()
        col_basename = re.match(r"([^=]+)=", to_explode).groups()[0]
        vals_str = re.search(r"{(.+)}", to_explode).groups()[0]
        vals_array = vals_str.split(' ')

        exploded_str = ""
        for (idx, val) in enumerate(vals_array):
            exploded_str += "{}{}={} ".format(col_basename, idx, val)

        vals_added = len(vals_array)
        if vals_added < array_lengths[col_basename]:
            for idx in range(vals_added, array_lengths[col_basename]):
                exploded_str += "{}{}=0 ".format(col_basename, idx)

        exploded_str = exploded_str[:-1]
        begin_idx = match.start()
        end_idx = match.end()

        string = string[:begin_idx] + exploded_str + string[end_idx:]

    return string

class BaseThermal(object):
    """Base class to parse trace.dat dumps.

    Don't use directly, create a subclass that defines the unique_word
    you want to match in the output"""
    def __init__(self, basepath, unique_word):
        if basepath is None:
            basepath = "."

        self.basepath = basepath
        self.data_csv = ""
        self.data_frame = pd.DataFrame()
        self.unique_word = unique_word

        if not os.path.isfile(os.path.join(basepath, "trace.txt")):
            self.__run_trace_cmd_report()

        self.__parse_into_csv()
        self.__create_data_frame()

    def __run_trace_cmd_report(self):
        """Run "trace-cmd report > trace.txt".

        Overwrites the contents of trace.txt if it exists."""
        from subprocess import check_output

        if not os.path.isfile(os.path.join(self.basepath, "trace.dat")):
            raise IOError("No such file or directory: trace.dat")

        previous_path = os.getcwd()
        os.chdir(self.basepath)

        # This would better be done with a context manager (i.e.
        # http://stackoverflow.com/a/13197763/970766)
        try:
            with open(os.devnull) as devnull:
                out = check_output(["trace-cmd", "report"], stderr=devnull)

        finally:
            os.chdir(previous_path)

        with open(os.path.join(self.basepath, "trace.txt"), "w") as fout:
            fout.write(out)

    def get_trace_array_lengths(self, fname):
        """Calculate the lengths of all arrays in the trace

        Returns a dict with the name of each array found in the trace
        as keys and their corresponding length as value

        """
        from collections import defaultdict

        pat_array = re.compile(r"([A-Za-z0-9_]+)={([^}]+)}")

        ret = defaultdict(int)

        with open(fname) as fin:
            for line in fin:
                if not re.search(self.unique_word, line):
                    continue

                while True:
                    match = re.search(pat_array, line)
                    if not match:
                        break

                    (array_name, array_elements) = match.groups()

                    array_len = len(array_elements.split(' '))

                    if array_len > ret[array_name]:
                        ret[array_name] = array_len

                    line = line[match.end():]

        return ret

    def __parse_into_csv(self):
        """Create a csv representation of the thermal data and store
        it in self.data_csv"""

        fin_fname = os.path.join(self.basepath, "trace.txt")

        array_lengths = self.get_trace_array_lengths(fin_fname)

        pat_timestamp = re.compile(r"([0-9]+\.[0-9]+):")
        pat_data = re.compile(r"[A-Za-z0-9_]+=([^ {]+)")
        pat_header = re.compile(r"([A-Za-z0-9_]+)=[^ ]+")
        pat_empty_array = re.compile(r"[A-Za-z0-9_]+=\{\} ")
        header = ""

        with open(fin_fname) as fin:
            for line in fin:
                if not re.search(self.unique_word, line):
                    continue

                line = line[:-1]

                timestamp_match = re.search(pat_timestamp, line)
                timestamp = timestamp_match.group(1)

                data_start_idx = re.search(r"[A-Za-z0-9_]+=", line).start()
                data_str = line[data_start_idx:]

                # Remove empty arrays from the trace
                data_str = re.sub(pat_empty_array, r"", data_str)

                data_str = trace_parser_explode_array(data_str, array_lengths)

                if not header:
                    header = re.sub(pat_header, r"\1", data_str)
                    header = re.sub(r" ", r",", header)
                    header = "Time," + header + "\n"
                    self.data_csv = header

                parsed_data = re.sub(pat_data, r"\1", data_str)
                parsed_data = re.sub(r",", r"", parsed_data)
                parsed_data = re.sub(r" ", r",", parsed_data)

                parsed_data = timestamp + "," + parsed_data + "\n"
                self.data_csv += parsed_data

    def __create_data_frame(self):
        """Create a pandas data frame for the run in self.data_frame"""
        if self.data_csv is "":
            self.data_frame = pd.DataFrame()
        else:
            self.data_frame = pd.read_csv(StringIO(self.data_csv))
            self.data_frame.set_index("Time", inplace=True)

    def normalize_time(self, basetime):
        """Substract basetime from the Time of the data frame"""
        self.data_frame.reset_index(inplace=True)
        self.data_frame["Time"] = self.data_frame["Time"] - basetime
        self.data_frame.set_index("Time", inplace=True)

class Thermal(BaseThermal):
    """Process the thermal framework data in a ftrace dump"""
    def __init__(self, path=None):
        super(Thermal, self).__init__(
            basepath=path,
            unique_word="thermal_temperature:",
        )

    def plot_temperature(self, control_temperature=None, title="", width=None,
                         height=None, ylim="range", ax=None, legend_label=""):
        """Plot the temperature.

        If control_temp is a pd.Series() representing the (possible)
        variation of control_temp during the run, draw it using a
        dashed yellow line.  Otherwise, only the temperature is
        plotted.

        """
        title = normalize_title("Temperature", title)

        setup_plot = False
        if not ax:
            ax = pre_plot_setup(width, height)
            setup_plot = True

        temp_label = normalize_title("Temperature", legend_label)
        (self.data_frame["temp"] / 1000).plot(ax=ax, label=temp_label)
        if control_temperature is not None:
            ct_label = normalize_title("Control", legend_label)
            control_temperature.plot(ax=ax, color="y", linestyle="--",
                           label=ct_label)

        if setup_plot:
            post_plot_setup(ax, title=title, ylim=ylim)
            plt.legend()

    def plot_temperature_hist(self, title=""):
        """Plot a temperature histogram"""

        temps = self.data_frame["temp"] / 1000
        title = normalize_title("Temperature", title)
        xlim = (0, temps.max())

        plot_hist(temps, title, 30, "Temperature", xlim, "default")

class ThermalGovernor(BaseThermal):
    """Process the power allocator data in a ftrace dump"""
    def __init__(self, path=None):
        super(ThermalGovernor, self).__init__(
            basepath=path,
            unique_word="thermal_power_allocator:",
        )

    def write_thermal_csv(self):
        """Write the csv info in thermal.csv"""
        with open("thermal.csv", "w") as fout:
            fout.write(self.data_csv)

    def plot_input_power(self, actor_order, title="", width=None, height=None, ax=None):
        """Plot input power

        actor_order is an array with the order in which the actors were registered.
        """

        dfr = self.data_frame
        in_cols = [s for s in dfr.columns if re.match("req_power[0-9]+", s)]

        plot_dfr = dfr[in_cols]
        # Rename the columns from "req_power0" to "A15" or whatever is
        # in actor_order.  Note that we can do it just with an
        # assignment because the columns are already sorted (i.e.:
        # req_power0, req_power1...)
        plot_dfr.columns = actor_order

        title = normalize_title("Input Power", title)

        if not ax:
            ax = pre_plot_setup(width, height)

        plot_dfr.plot(ax=ax)
        post_plot_setup(ax, title=title)

    def plot_output_power(self, actor_order, title="", width=None, height=None, ax=None):
        """Plot output power

        actor_order is an array with the order in which the actors were registered.
        """

        out_cols = [s for s in self.data_frame.columns
                    if re.match("granted_power[0-9]+", s)]

        # See the note in plot_input_power()
        plot_dfr = self.data_frame[out_cols]
        plot_dfr.columns = actor_order

        title = normalize_title("Output Power", title)

        if not ax:
            ax = pre_plot_setup(width, height)

        plot_dfr.plot(ax=ax)
        post_plot_setup(ax, title=title)

    def plot_inout_power(self, title="", width=None, height=None):
        """Make multiple plots showing input and output power for each actor"""
        dfr = self.data_frame

        actors = []
        for col in dfr.columns:
                match = re.match("P(.*)_in", col)
                if match and col != "Ptot_in":
                    actors.append(match.group(1))

        for actor in actors:
            cols = ["P" + actor + "_in", "P" + actor + "_out"]
            this_title = normalize_title(actor, title)
            dfr[cols].plot(title=this_title)
