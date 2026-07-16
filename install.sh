# Check number of arguments, if its not 1 then give usage
if [ "$#" -ne 1 ]; then
    echo "Usage: $0 <environment_name>"
    exit 1
fi

# Create a new environment for the project, given as the first argument.
conda create -n $1 python=3.11
source activate $1

# Install dependencies.
# Note: Some project dependencies are implicit, as they are installed
#       alongside one of the following packages.
conda install -c conda-forge pyresample netCDF4 basemap jsonschema frozendict

# Install project packages.
python -m pip install -e .

# Write environment variables that are used by the project.
export PYTHONHASHSEED=0
export ARRHENIUS_MAIN_PATH=`pwd`

# Download data files from remote sources
download() {
    local url=$1
    local dest="data/models/$(basename "$url")"
    echo "Downloading $url..."
    if ! wget -nc -P data/models "$url"; then
        echo "ERROR: Failed to download $url" >&2
        exit 1
    fi
    echo "OK: $dest"
}

download https://berkeley-earth-temperature.s3.us-west-1.amazonaws.com/Global/Gridded/Land_and_Ocean_LatLong1.nc
download ftp://ftp.cdc.noaa.gov/Datasets/ncep.reanalysis.derived/pressure/air.mon.mean.nc
download ftp://ftp.cdc.noaa.gov/Datasets/ncep.reanalysis.derived/pressure/rhum.mon.mean.nc

echo "Now run: conda activate $1"
