"""Device capability descriptors.

These models describe what operations a device supports, allowing runtime
introspection of device features. This is especially useful when working
with different protocol backends that may have varying feature sets.
"""

from pydantic import BaseModel, Field


class MountCapabilities(BaseModel):
    """Describes what a mount can do."""

    can_slew: bool = Field(default=True, description="Can slew to coordinates")
    can_slew_async: bool = Field(default=True, description="Supports async slewing")
    can_sync: bool = Field(default=True, description="Can sync to coordinates")
    can_park: bool = Field(default=True, description="Can park")
    can_unpark: bool = Field(default=True, description="Can unpark")
    can_find_home: bool = Field(default=False, description="Can find home position")
    can_pulse_guide: bool = Field(default=False, description="Supports pulse guiding")
    can_set_tracking: bool = Field(default=True, description="Can enable/disable tracking")
    can_set_tracking_rate: bool = Field(default=False, description="Can set tracking rate")
    can_slew_altaz: bool = Field(default=False, description="Can slew to Alt/Az")
    has_pier_side: bool = Field(default=False, description="Reports pier side (GEM)")
    alignment_mode: str = Field(
        default="unknown", description="Alignment mode: altaz, polar, german"
    )
    max_slew_rate: float = Field(default=0.0, description="Max slew rate in deg/sec")


class CameraCapabilities(BaseModel):
    """Describes what a camera can do."""

    can_abort_exposure: bool = Field(default=True, description="Can abort exposure")
    can_stop_exposure: bool = Field(default=False, description="Can stop exposure early")
    can_set_gain: bool = Field(default=True, description="Has adjustable gain")
    can_set_offset: bool = Field(default=False, description="Has adjustable offset")
    can_set_binning: bool = Field(default=True, description="Supports binning")
    can_subframe: bool = Field(default=True, description="Supports subframe readout")
    can_fast_readout: bool = Field(default=False, description="Has fast readout mode")
    has_shutter: bool = Field(default=False, description="Has mechanical shutter")
    has_cooler: bool = Field(default=False, description="Has TEC cooler")
    has_filter_wheel: bool = Field(default=False, description="Has integrated filter wheel")
    is_color: bool = Field(default=False, description="Color sensor (Bayer)")
    max_bin_x: int = Field(default=1, ge=1, description="Max horizontal binning")
    max_bin_y: int = Field(default=1, ge=1, description="Max vertical binning")
    sensor_width: int = Field(default=0, ge=0, description="Sensor width in pixels")
    sensor_height: int = Field(default=0, ge=0, description="Sensor height in pixels")
    pixel_size_x: float = Field(default=0.0, ge=0, description="Pixel width in micrometers")
    pixel_size_y: float = Field(default=0.0, ge=0, description="Pixel height in micrometers")
    min_exposure: float = Field(default=0.0, ge=0, description="Minimum exposure in seconds")
    max_exposure: float = Field(default=3600.0, gt=0, description="Maximum exposure in seconds")
    supported_gains: list[int] = Field(default_factory=list, description="Available gain values")
    bit_depth: int = Field(default=16, description="ADC bit depth")


class FocuserCapabilities(BaseModel):
    """Describes what a focuser can do."""

    can_absolute: bool = Field(default=True, description="Supports absolute positioning")
    can_relative: bool = Field(default=True, description="Supports relative moves")
    can_halt: bool = Field(default=True, description="Can halt movement")
    has_temperature: bool = Field(default=False, description="Has temperature sensor")
    has_temp_compensation: bool = Field(default=False, description="Supports temp compensation")
    max_step: int = Field(default=0, ge=0, description="Maximum position in steps")
    step_size: float = Field(default=0.0, ge=0, description="Step size in micrometers")


class FilterWheelCapabilities(BaseModel):
    """Describes what a filter wheel can do."""

    num_positions: int = Field(default=0, ge=0, description="Number of filter slots")
    filter_names: list[str] = Field(default_factory=list, description="Filter names by position")
    has_focus_offsets: bool = Field(
        default=False, description="Supports per-filter focus offsets"
    )
    focus_offsets: list[int] = Field(
        default_factory=list, description="Focus offsets per filter"
    )
