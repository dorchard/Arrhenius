from os import path
from typing import Optional, List, Tuple

from data.resources import OUTPUT_REL_PATH
from data.reader import NetCDFReader
from data.writer import NetCDFWriter
from data.grid import LatLongGrid, GridDimensions,\
    extract_multidimensional_grid_variable

from core.configuration import global_config, ArrheniusConfig
from core.output_config import global_output_center, ReportDatatype, Debug,\
    DATASET_VARS, IMAGES

from pathlib import Path
from mpl_toolkits.basemap import Basemap

import matplotlib
matplotlib.use("agg")
import matplotlib.pyplot as plt
import numpy as np


OUTPUT_FULL_PATH = path.join(Path('.').absolute(), OUTPUT_REL_PATH)

# Keys in the dictionary below.
VAR_TYPE = "Type"

VAR_ATTRS = "Attrs"
VAR_UNITS = "Units"
VAR_DESCRIPTION = "Desc"

# Data describing each variable in the dataset.
VARIABLE_METADATA = {
    ReportDatatype.REPORT_TEMP.value: {
        VAR_TYPE: np.float32,
        VAR_ATTRS: {
            VAR_UNITS: "Degrees Celsius",
            VAR_DESCRIPTION: "Final temperature of the grid cell that is"
                             "centered at the associated latitude and"
                             "longitude coordinates"
        }
    },
    ReportDatatype.REPORT_TEMP_CHANGE.value: {
        VAR_TYPE: np.float32,
        VAR_ATTRS: {
            VAR_UNITS: "Degrees Celsius",
            VAR_DESCRIPTION: "Temperature change observed due to CO2 change"
                             "for the grid cell that is centered at the"
                             "associated latitude and longitude coordinates"
        }
    },
    ReportDatatype.REPORT_HUMIDITY.value: {
        VAR_TYPE: np.float32,
        VAR_ATTRS: {
            VAR_UNITS: "Percent Saturation",
            VAR_DESCRIPTION: "Final relative humidity of the grid cell"
                             "centered at the associated latitude and"
                             "longitude coordinates"
        }
    },
    ReportDatatype.REPORT_ALBEDO.value: {
        VAR_TYPE: np.float32,
        VAR_ATTRS: {
            VAR_UNITS: "Decimal Absorption",
            VAR_DESCRIPTION: "Percent of incoming solar energy absorbed"
                             "by the Earth's surface within the grid cell"
                             "centered at the associated latitude and"
                             "longitude coordinates"
        }
    },
}


def image_file_name(basename: str,
                    config: 'ArrheniusConfig') -> str:
    """
    Returns the name of an image file generated from a model run that used
    config as its configuration settings, with basename as an additional
    specification that is placed inside the name. This specification should
    describe which parts of the model run are included in the image, such
    as time units and/or levels, and which variable is being displayed.

    :param basename:
        A description of the data the image will display
    :param config:
        Configuration options for the model run the image is based on
    :return:
        A name for the image file
    """
    # File names are defined by the model's run ID and the colour scale.
    # Periods are replaced with commas in colorbar bounds to avoid improper
    # interpretation as part of a file extension.
    return "_".join([config.run_id(), basename,
                     "[{}x{}]".format(*config.colorbar())])\
              .replace(".", ",")


def get_image_directory(parent: str,
                        run_id: str,
                        var_name: str,
                        scale: Tuple[float, float],
                        create: bool = True) -> str:
    """
    Returns a file path to the directory that stores images from a model
    run titled run_id, representing variable var_name, with colorbar
    boundaries as given in scale. This directory is placed inside parent,
    which can be a directory for whole model output.

    By default, the directory structure will be created if it does not exist.
    If the optional parameter create is given the value False, the directory
    structure will not be created. This may save computation steps, but
    exercise caution when using this option.

    :param parent:
        The directory in which the output directory is to be placed
    :param run_id:
        The name of the model run from which the images are being produced
    :param var_name:
        The name of the variable being rendered in the images
    :param scale:
        Lower and upper bounds on the values on the colorbar of all the images
    :param create:
        Whether or not to create the directory structure if it does not exist
    :return:
        A path to the directory where images are/should be placed
    """
    # Topmost directory contains all images produced from the model run
    # with colour bounds equivalent to scale.
    scale_dir_name = "_".join([run_id, "[{}x{}]".format(*scale)])
    scale_dir_path = path.join(parent, scale_dir_name)

    # Lower-level directory contains images that represent variable var_name.
    out_dir_path = path.join(scale_dir_path, var_name)

    if create:
        # Create the new directory structure if specified.
        Path(scale_dir_path).mkdir(exist_ok=True)
        Path(out_dir_path).mkdir(exist_ok=True)

    return out_dir_path


class ModelImageRenderer:
    """
    A converter between gridded climate data and image visualizations of the
    data. Displays data in the form of nested lists or arrays as an overlay
    on a world map projection.
    """
    def __init__(self: 'ModelImageRenderer',
                 data: np.ndarray) -> None:
        """
        Instantiate a new ModelImageReader.

        Data to display is provided through the data parameter. This parameter
        may either by an array, or an array-like structure such as a nested
        list. the There must be three dimensions to the data: time first,
        followed by latitude and longitude.

        :param data:
            An array-like structure of numeric values, representing temperature
            over a globe
        """
        self._data = data
        self._grid = GridDimensions((len(data), len(data[0])), "count")

        # Some parameters for the visualization are also left as attributes.
        self._continent_linewidth = 0.5
        self._lat_long_linewidth = 0.1

    def save_image(self: 'ModelImageRenderer',
                   out_path: str,
                   min_max_grades: Tuple[float, float] = (-8, 8)) -> None:
        """
        Produces a .PNG formatted image file containing the gridded data
        overlaid on a map projection.

        The map is displayed in equirectangular projection, labelled with
        lines of latitude and longitude at the intersection between
        neighboring grid cells. The grid cells are filled in with a colour
        denoting the magnitude of the temperature at that cell.

        The optional min_max_grades parameter specifies the lower bound and
        the upper bound of the range of values for which different colours
        are assigned. Any grid cell with a temperature value below the first
        element of min_max_grades will be assigned the same colour. The same
        applies to any cell with a temperature greater than min_max_grades[1].
        The default boundaries are -60 and 40.

        The image is saved at the specified absolute or relative filepath.

        :param out_path:
            The location where the image file is created
        :param min_max_grades:
            A tuple containing the boundary values for the colorbar shown in
            the image file
        """
        if min_max_grades is not None and len(min_max_grades) != 2:
            raise ValueError("Color grade boundaries must be given in a tuple"
                             "of length 2 (is length {})"
                             .format(len(min_max_grades)))
        # Create an empty world map in equirectangular projection.
        map = Basemap(llcrnrlat=-90, llcrnrlon=-180,
                      urcrnrlat=90, urcrnrlon=180)
        map.drawcoastlines(linewidth=self._continent_linewidth)

        # Construct a grid from the horizontal and vertical sizes of the cells.
        grid_by_width = self._grid.dims_by_width()

        lat_val = -90.0
        lats = []
        while lat_val <= 90:
            lats.append(lat_val)
            lat_val += grid_by_width[0]

        lon_val = -180.0
        lons = []
        while lon_val <= 180:
            lons.append(lon_val)
            lon_val += grid_by_width[1]

        map.drawparallels(lats, linewidth=self._lat_long_linewidth)
        map.drawmeridians(lons, linewidth=self._lat_long_linewidth)
        x, y = map(lons, lats)
        x, y = np.asarray(x), np.asarray(y)

        # Overlap the gridded data on top of the map, and display a colour
        # legend with the appropriate boundaries.
        img_bin = map.pcolormesh(x, y, self._data, cmap=plt.cm.get_cmap("jet"))

        map.colorbar(img_bin)
        plt.clim(min_max_grades[0], min_max_grades[1])

        fig = plt.gcf()
        fig.canvas.draw()

        pixels = fig.canvas.tostring_argb()
        img = np.frombuffer(pixels, dtype=np.uint8).copy()
        img = img.reshape(fig.canvas.get_width_height()[::-1] + (4,))[:, :, 1:]
        img = img[118:-113, 80:-30, :]

        alphas = np.ones(img.shape[:2], dtype=np.uint8) * 255
        alphas[:, -65:-57] = 0
        alphas[:9, :-43] = 0
        alphas[-8:, :-43] = 0

        for i in range(img.shape[0]):
            for j in range(img.shape[1] - 43, img.shape[1]):
                pixel = tuple(img[i, j, :])
                # if sum(pixel) == 765:
                if sum(pixel) < 450 and j >= img.shape[1] - 33:
                    img[i, j, :] = [147, 149, 152]
                elif j >= img.shape[1] - 33 or i < 9 or i > img.shape[0] - 9:
                    alphas[i, j] = 0

        img = np.dstack((img, alphas))
        plt.imsave(fname=out_path, arr=img)
        plt.close()

        # plt.savefig(fname=out_path)


def write_image_type(data: np.ndarray,
                     parent_path: str,
                     data_type: str,
                     config: 'ArrheniusConfig') -> bool:
    """
    Write out a category of output, given by the parameter data, to a
    directory with the name given by output_path. One image file will
    be produced for every index in the highest-level dimension in the
    data. Returns True iff a new image was produced that was not already
    present on disk.

    The third parameter specifies the name of the variable being
    represented by this set of images. The fourth parameter is a
    configuration set belonging to the model run the images will be
    based on. Configuration will determine the names of the output files.

    :param data:
        A single-variable grid derived from Arrhenius model output
    :param output_path:
        The directory where image files will be stored
    :param data_type:
        The name of the variable on which the data is based
    :param config:
        Configuration options for the previously-run model run
    :return:
        True iff a new image file was produced
    """
    output_center = global_output_center()
    output_center.submit_output(Debug.PRINT_NOTICES,
                                "Preparing to write {} images"
                                .format(data_type))

    output_path = \
        get_image_directory(parent_path, config.run_id(), data_type,
                            config.colorbar(), create=True)
    file_ext = '.png'

    annual_avg = np.array([np.mean(data, axis=0)])
    data = np.concatenate([annual_avg, data], axis=0)

    created = False

    # Write an image file for each time segment.
    for i in range(len(data)):
        base_name = data_type + "_" + str(i)
        img_name = image_file_name(base_name, config) + file_ext
        img_path = path.join(output_path, img_name)

        new_created = not Path(img_path).is_file()

        if new_created:
            # Produce and save the image.
            output_center.submit_output(Debug.PRINT_NOTICES,
                                        "\tSaving image file {}...".format(i))
            g = ModelImageRenderer(data[i])
            g.save_image(img_path, config.colorbar())
            created = True

    return created


class ModelOutput:
    """
    A general-purpose center for all forms of output. Responsible for
    organization of program output into folders.

    The output of a program is defined as the temperature data produced by
    a run of the model. This data may be saved in the form of a data file
    (such as a NetCDF file) and/or as image representations, and/or in other
    data formats.

    All of these output types are produced side-by-side, and stored in their
    own directory to keep data separate from different model runs.
    """

    def __init__(self: 'ModelOutput',
                 data: List['LatLongGrid']) -> None:
        """
        Instantiate a new ModelOutput object.

        Model data is provided through the data parameter, through a list of
        grid objects. Each grid in the list represents a segment of time, such
        as a month or a season. All grids must have the same dimensions.

        :param data:
            A list of latitude-longitude grids of data
        """
        # Create output directory if it does not already exist.
        parent_out_dir = Path(OUTPUT_FULL_PATH)
        parent_out_dir.mkdir(exist_ok=True)

        self._data = data
        self._grid = data[0].dimensions()
        self._dataset = NetCDFWriter()

    def write_dataset(self: 'ModelOutput',
                      data: List['LatLongGrid'],
                      dir_path: str,
                      dataset_name: str) -> None:
        """
        Produce a NetCDF dataset, with the name given by dataset_name.nc,
        containing the variables in the data parameter that the output
        controller allows. The dataset will be written to the specified
        path in the file system.

        The dataset contains all the dimensions that are used in the data
        (e.g. time, latitude, longitude) as well as variables including
        final temperature, temperature change, humidity, etc. according
        to which of the ReportDatatype output types are enabled in the
        current output controller.

        :param data:
            Output from an Arrhenius model run
        :param dir_path:
            The directory where the dataset will be written
        :param dataset_name:
            The name of the dataset
        """
        # Write the data out to a NetCDF file in the output directory.
        grid_by_count = self._grid.dims_by_count()
        output_path = path.join(dir_path, dataset_name)

        global_output_center().submit_output(Debug.PRINT_NOTICES,
                                             "Writing NetCDF dataset...")
        self._dataset.global_attribute("description", "Output for an"
                                                      "Arrhenius model run.")\
            .dimension('time', np.int32, len(data), (0, len(data)))\
            .dimension('latitude', np.int32, grid_by_count[0], (-90, 90)) \
            .dimension('longitude', np.int32, grid_by_count[1], (-180, 180)) \

        for output_type in ReportDatatype:
            variable_data =\
                extract_multidimensional_grid_variable(data,
                                                       output_type.value)
            global_output_center().submit_output(output_type, variable_data,
                                                 output_type.value)

        self._dataset.write(output_path)

    def write_dataset_variable(self: 'ModelOutput',
                               data: np.ndarray,
                               data_type: str) -> None:
        """
        Prepare to write data into a variable by the name of data_type
        in this instance's NetCDF dataset file. Apply this variable's
        dimensions and type, along with several attributes.

        :param data:
            A single-variable grid taken from Arrhenius model output
        :param data_type:
            The name of the variable as it will appear in the dataset
        """
        dims_map = [
            [],
            ['latitude'],
            ['latitude', 'longitude'],
            ['time', 'latitude', 'longitude'],
            ['time', 'level', 'latitude', 'longitude']
        ]

        global_output_center().submit_output(Debug.PRINT_NOTICES,
                                             "Writing {} to dataset"
                                             .format(data_type))
        variable_type = VARIABLE_METADATA[data_type][VAR_TYPE]
        self._dataset.variable(data_type, variable_type, dims_map[data.ndim])

        for attr, val in VARIABLE_METADATA[data_type][VAR_ATTRS].items():
            self._dataset.variable_attribute(data_type, attr, val)

        self._dataset.data(data_type, data)

    def write_images(self: 'ModelOutput',
                     data: List['LatLongGrid'],
                     output_path: str,
                     config: 'ArrheniusConfig') -> None:
        """
        Produce a series of maps displaying some of the results of an
        Arrhenius model run according to what variable the output controller
        allows. Images are stored in a directory given by output_path.

        One image will be produced per time segment per variable for which
        output is allowed by the output controller, based on which
        ReportDatatype output types are enabled. Names of these image files
        are based on variable and time unit, as well as config.

        :param data:
            The output from an Arrhenius model run
        :param output_path:
            The directory where image files will be stored
        :param config:
            Configuration options for the model run
        """
        output_controller = global_output_center()

        # Attempt to output images for each variable output type.
        for output_type in ReportDatatype:
            var_name = output_type.value
            variable = extract_multidimensional_grid_variable(data, var_name)

            output_controller.submit_output(output_type, variable,
                                            output_path,
                                            var_name,
                                            config)

    def write_output(self: 'ModelOutput',
                     config: 'ArrheniusConfig') -> None:
        """
        Produce NetCDF data files and image files from the provided data,
        located in a new directory for this output set. The name of the
        directory is based on config.

        One image file is created per time segment in the data. In the
        case of Arrhenius' model, this is one per season. Only one NetCDF data
        file is produced, in which all time segments are present.

        :param config:
            Configuration options for the model run
        """
        run_title = config.run_id()

        # Create a directory for this model output if none exists already.
        out_dir_path = path.join(OUTPUT_FULL_PATH, run_title)
        out_dir = Path(out_dir_path)
        out_dir.mkdir(exist_ok=True)

        output_controller = global_output_center()
        output_controller.submit_collection_output((DATASET_VARS,),
                                                   self._data,
                                                   out_dir_path,
                                                   run_title + ".nc")
        output_controller.submit_collection_output((IMAGES,),
                                                   self._data,
                                                   out_dir_path,
                                                   config)


def save_from_dataset(dataset_parent: str,
                      var_name: str,
                      time_seg: Optional[int],
                      config: 'ArrheniusConfig') -> bool:
    """
    Produce a set of image outputs based on a dataset, written by a
    previous run of the Arrhenius model that used config as its
    configuration set. This dataset is stored in the directory given by
    the path dataset_parent.

    The images produced are under the variable var_name in the dataset,
    and only in the time unit given by time_seg. If time_seg is 0, then
    one image will be produced containing averages over the datapoints
    in all time units. If time_seg is None, then an image will be produced
    for every valid time segment.

    Returns True iff a new image was produced by this call, i.e. if it
    did not exist prior to the call.

    :param dataset_parent:
        A path to the directory containing the dataset
    :param var_name:
        The variable from the dataset that will be used to generate the images
    :param time_seg:
        An integer specifying which time unit to use data from
    :param config:
        Configuration options for the previously-run model run
    :return:
        True iff a new image file was created
    """
    run_id = config.run_id()
    # Locate or create a directory to contain image files.

    if time_seg is None:
        # Assume at least one image needs to be produced, and immediately
        # read in data in preparation for that.
        dataset_path = path.join(dataset_parent, run_id + ".nc")
        reader = NetCDFReader(dataset_path)
        data = reader.collect_untimed_data(var_name)
        reader.close()

        # Write all images for variable var_name to the proper destination.
        return write_image_type(data, dataset_parent, var_name, config)
    else:
        # Create an output directory for the new images and get its name.
        parent_path = \
            get_image_directory(dataset_parent, run_id, var_name,
                                config.colorbar(), create=True)

        # Detect if the desired image file already exists.
        base_name = var_name + "_" + str(time_seg)
        file_name = image_file_name(base_name, config) + ".png"
        img_path = path.join(parent_path, file_name)

        created = not Path(img_path).is_file()

        if created:
            # Locate the dataset and read the desired variable from it.
            dataset_path = path.join(dataset_parent, run_id + ".nc")
            reader = NetCDFReader(dataset_path)
            data = reader.collect_untimed_data(var_name)

            # Extract only the requested parts of the data.
            if time_seg == 0:
                selected_time_data = data.mean(axis=0)
            else:
                selected_time_data = data[time_seg - 1]

            # Write the new image file.
            img_writer = ModelImageRenderer(selected_time_data)
            img_writer.save_image(img_path, config.colorbar())
            reader.close()

        return created


def write_model_output(data: List['LatLongGrid']) -> None:
    """
    Write the results of a model run (data) to disk, in the form of a
    NetCDF dataset and a series of image files.

    Location and output specifications are given by thread-specific
    global configurations, which can be accessed using the global_config
    and set_configuration functions in the configuration module, and the
    corresponding functions in output_config.

    :param data:
        The output from an Arrhenius model run
    """
    writer = ModelOutput(data)
    controller = global_output_center()

    # Upload collection handlers for dataset and image file collections.
    controller.register_collection(DATASET_VARS, handler=writer.write_dataset)
    controller.register_collection(IMAGES, handler=writer.write_images)

    # Change several output type handlers within each collection.
    for output_type in ReportDatatype:
        controller.change_handler_if_enabled(output_type,
                                             (DATASET_VARS,),
                                             writer.write_dataset_variable)
        controller.change_handler_if_enabled(output_type,
                                             (IMAGES,),
                                             write_image_type)

    writer.write_output(global_config())
