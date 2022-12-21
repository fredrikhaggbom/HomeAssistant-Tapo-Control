import datetime

from homeassistant.core import HomeAssistant
from homeassistant.components.ffmpeg import CONF_EXTRA_ARGUMENTS
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CONF_IP_ADDRESS,
    CONF_USERNAME,
    CONF_PASSWORD,
    EVENT_HOMEASSISTANT_STOP,
)
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import (
    CONF_RTSP_TRANSPORT,
    ENABLE_SOUND_DETECTION,
    CONF_CUSTOM_STREAM,
    LOGGER,
    DOMAIN,
    ENABLE_MOTION_SENSOR,
    CLOUD_PASSWORD,
    ENABLE_STREAM,
    ENABLE_TIME_SYNC,
    RTSP_TRANS_PROTOCOLS,
    SOUND_DETECTION_DURATION,
    SOUND_DETECTION_PEAK,
    SOUND_DETECTION_RESET,
    TIME_SYNC_PERIOD,
    UPDATE_CHECK_PERIOD,
)
from .utils import (
    registerController,
    getCamData,
    setupOnvif,
    setupEvents,
    update_listener,
    initOnvifEvents,
    syncTime,
    getLatestFirmwareVersion,
)


async def async_setup(hass: HomeAssistant, config: dict):
    """Set up the Tapo: Cameras Control component from YAML."""
    return True


async def async_migrate_entry(hass, config_entry: ConfigEntry):
    """Migrate old entry."""
    LOGGER.debug("Migrating from version %s", config_entry.version)

    if config_entry.version == 1:

        new = {**config_entry.data}
        new[ENABLE_MOTION_SENSOR] = True
        new[CLOUD_PASSWORD] = ""

        config_entry.data = {**new}

        config_entry.version = 2

    if config_entry.version == 2:

        new = {**config_entry.data}
        new[CLOUD_PASSWORD] = ""

        config_entry.data = {**new}

        config_entry.version = 3

    if config_entry.version == 3:

        new = {**config_entry.data}
        new[ENABLE_STREAM] = True

        config_entry.data = {**new}

        config_entry.version = 4

    if config_entry.version == 4:

        new = {**config_entry.data}
        new[ENABLE_TIME_SYNC] = False

        config_entry.data = {**new}

        config_entry.version = 5

    if config_entry.version == 5:

        new = {**config_entry.data}
        new[ENABLE_SOUND_DETECTION] = False
        new[SOUND_DETECTION_PEAK] = -50
        new[SOUND_DETECTION_DURATION] = 1
        new[SOUND_DETECTION_RESET] = 10

        config_entry.data = {**new}

        config_entry.version = 6

    if config_entry.version == 6:

        new = {**config_entry.data}
        new[CONF_EXTRA_ARGUMENTS] = ""

        config_entry.data = {**new}

        config_entry.version = 7

    if config_entry.version == 7:

        new = {**config_entry.data}
        new[CONF_CUSTOM_STREAM] = ""

        config_entry.data = {**new}

        config_entry.version = 8

    if config_entry.version == 8:

        new = {**config_entry.data}
        new[CONF_RTSP_TRANSPORT] = RTSP_TRANS_PROTOCOLS[0]

        config_entry.data = {**new}

        config_entry.version = 9

    LOGGER.info("Migration to version %s successful", config_entry.version)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    await hass.config_entries.async_forward_entry_unload(entry, "binary_sensor")
    await hass.config_entries.async_forward_entry_unload(entry, "button")
    await hass.config_entries.async_forward_entry_unload(entry, "camera")
    await hass.config_entries.async_forward_entry_unload(entry, "light")
    await hass.config_entries.async_forward_entry_unload(entry, "number")
    await hass.config_entries.async_forward_entry_unload(entry, "select")
    await hass.config_entries.async_forward_entry_unload(entry, "switch")
    await hass.config_entries.async_forward_entry_unload(entry, "update")

    if hass.data[DOMAIN][entry.entry_id]["events"]:
        await hass.data[DOMAIN][entry.entry_id]["events"].async_stop()
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry):
    """Set up the Tapo: Cameras Control component from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    host = entry.data.get(CONF_IP_ADDRESS)
    username = entry.data.get(CONF_USERNAME)
    password = entry.data.get(CONF_PASSWORD)
    motionSensor = entry.data.get(ENABLE_MOTION_SENSOR)
    cloud_password = entry.data.get(CLOUD_PASSWORD)
    enableTimeSync = entry.data.get(ENABLE_TIME_SYNC)

    try:
        if cloud_password != "":
            tapoController = await hass.async_add_executor_job(
                registerController, host, "admin", cloud_password
            )
        else:
            tapoController = await hass.async_add_executor_job(
                registerController, host, username, password
            )

        async def async_update_data():
            LOGGER.debug("async_update_data - entry")
            host = entry.data.get(CONF_IP_ADDRESS)
            username = entry.data.get(CONF_USERNAME)
            password = entry.data.get(CONF_PASSWORD)
            motionSensor = entry.data.get(ENABLE_MOTION_SENSOR)
            enableTimeSync = entry.data.get(ENABLE_TIME_SYNC)

            # motion detection retries
            if motionSensor or enableTimeSync:
                LOGGER.debug("Motion sensor or time sync is enabled.")
                if (
                    not hass.data[DOMAIN][entry.entry_id]["isChild"]
                    and not hass.data[DOMAIN][entry.entry_id]["isParent"]
                ):
                    if (
                        not hass.data[DOMAIN][entry.entry_id]["eventsDevice"]
                        or not hass.data[DOMAIN][entry.entry_id]["onvifManagement"]
                    ):
                        LOGGER.debug("Setting up subscription to motion sensor...")
                        # retry if connection to onvif failed
                        LOGGER.debug("Initiating onvif.")
                        onvifDevice = await initOnvifEvents(
                            hass, host, username, password
                        )
                        LOGGER.debug(onvifDevice)
                        hass.data[DOMAIN][entry.entry_id]["eventsDevice"] = onvifDevice[
                            "device"
                        ]
                        hass.data[DOMAIN][entry.entry_id][
                            "onvifManagement"
                        ] = onvifDevice["device_mgmt"]
                        if motionSensor:
                            await setupOnvif(hass, entry)
                    elif (
                        not hass.data[DOMAIN][entry.entry_id]["eventsSetup"]
                        and motionSensor
                    ):
                        LOGGER.debug(
                            "Setting up subcription to motion sensor events..."
                        )
                        # retry if subscription to events failed
                        hass.data[DOMAIN][entry.entry_id][
                            "eventsSetup"
                        ] = await setupEvents(hass, entry)
                    else:
                        LOGGER.debug("Motion sensor: OK")
                else:
                    LOGGER.debug(
                        "Not updating motion sensor because device is child or parent."
                    )

                if (
                    hass.data[DOMAIN][entry.entry_id]["onvifManagement"]
                    and enableTimeSync
                ):
                    ts = datetime.datetime.utcnow().timestamp()
                    if (
                        ts - hass.data[DOMAIN][entry.entry_id]["lastTimeSync"]
                        > TIME_SYNC_PERIOD
                    ):
                        # todo: add for child devices too
                        await syncTime(hass, entry.entry_id)
                ts = datetime.datetime.utcnow().timestamp()
                if (
                    ts - hass.data[DOMAIN][entry.entry_id]["lastFirmwareCheck"]
                    > UPDATE_CHECK_PERIOD
                ):
                    # todo: add for child devices too
                    hass.data[DOMAIN][entry.entry_id][
                        "latestFirmwareVersion"
                    ] = await getLatestFirmwareVersion(
                        hass, entry, hass.data[DOMAIN][entry.entry_id]["controller"]
                    )

            # cameras state
            someCameraEnabled = False
            for entity in hass.data[DOMAIN][entry.entry_id]["entities"]:
                if entity["entity"]._enabled:
                    someCameraEnabled = True

            if someCameraEnabled:

                # Update data for all controllers
                updateDataForAllControllers = {}
                for controller in hass.data[DOMAIN][entry.entry_id]["allControllers"]:
                    try:
                        updateDataForAllControllers[controller] = await getCamData(
                            hass, controller
                        )
                    except Exception as e:
                        updateDataForAllControllers[controller] = False
                        LOGGER.error(e)

                hass.data[DOMAIN][entry.entry_id][
                    "camData"
                ] = updateDataForAllControllers[tapoController]

                LOGGER.debug("Updating entities...")
                for entity in hass.data[DOMAIN][entry.entry_id]["entities"]:
                    if entity["entity"]._enabled:
                        entity["camData"] = updateDataForAllControllers[
                            entity["entry"]["controller"]
                        ]
                        entity["entity"].updateTapo(
                            updateDataForAllControllers[entity["entry"]["controller"]]
                        )
                        entity["entity"].async_schedule_update_ha_state(True)
                        # start noise detection
                        if (
                            not hass.data[DOMAIN][entry.entry_id]["noiseSensorStarted"]
                            and entity["entity"]._is_noise_sensor
                            and entity["entity"]._enable_sound_detection
                        ):
                            await entity["entity"].startNoiseDetection()
                if ("updateEntity" in hass.data[DOMAIN][entry.entry_id]) and hass.data[
                    DOMAIN
                ][entry.entry_id]["updateEntity"]._enabled:
                    hass.data[DOMAIN][entry.entry_id]["updateEntity"].updateTapo(
                        camData
                    )
                    hass.data[DOMAIN][entry.entry_id][
                        "updateEntity"
                    ].async_schedule_update_ha_state(True)

        tapoCoordinator = DataUpdateCoordinator(
            hass, LOGGER, name="Tapo resource status", update_method=async_update_data,
        )

        camData = await getCamData(hass, tapoController)

        hass.data[DOMAIN][entry.entry_id] = {
            "controller": tapoController,
            "allControllers": [tapoController],
            "update_listener": entry.add_update_listener(update_listener),
            "coordinator": tapoCoordinator,
            "camData": camData,
            "lastTimeSync": 0,
            "lastFirmwareCheck": 0,
            "latestFirmwareVersion": False,
            "motionSensorCreated": False,
            "eventsDevice": False,
            "onvifManagement": False,
            "eventsSetup": False,
            "events": False,
            "eventsListener": False,
            "entities": [],
            "noiseSensorStarted": False,
            "name": camData["basic_info"]["device_alias"],
            "childDevices": [],
            "isChild": False,
            "isParent": False,
        }

        if camData["childDevices"] is False or camData["childDevices"] is None:
            hass.async_create_task(
                hass.config_entries.async_forward_entry_setup(entry, "camera")
            )
        else:
            hass.data[DOMAIN][entry.entry_id]["isParent"] = True
            for childDevice in camData["childDevices"]["child_device_list"]:
                tapoChildController = await hass.async_add_executor_job(
                    registerController,
                    host,
                    "admin",
                    cloud_password,
                    cloud_password,
                    "",
                    childDevice["device_id"],
                )
                hass.data[DOMAIN][entry.entry_id]["allControllers"].append(
                    tapoChildController
                )
                childCamData = await getCamData(hass, tapoChildController)
                hass.data[DOMAIN][entry.entry_id]["childDevices"].append(
                    {
                        "controller": tapoChildController,
                        "coordinator": tapoCoordinator,
                        "camData": childCamData,
                        "lastTimeSync": 0,
                        "lastFirmwareCheck": 0,
                        "latestFirmwareVersion": False,
                        "motionSensorCreated": False,
                        "entities": [],
                        "name": camData["basic_info"]["device_alias"],
                        "childDevices": [],
                        "isChild": True,
                        "isParent": False,
                    }
                )

        hass.async_create_task(
            hass.config_entries.async_forward_entry_setup(entry, "switch")
        )
        """
        hass.async_create_task(
            hass.config_entries.async_forward_entry_setup(entry, "button")
        )
        hass.async_create_task(
            hass.config_entries.async_forward_entry_setup(entry, "light")
        )
        hass.async_create_task(
            hass.config_entries.async_forward_entry_setup(entry, "number")
        )
        hass.async_create_task(
            hass.config_entries.async_forward_entry_setup(entry, "select")
        )
        hass.async_create_task(
            hass.config_entries.async_forward_entry_setup(entry, "update")
        )
        hass.async_create_task(
            hass.config_entries.async_forward_entry_setup(entry, "binary_sensor")
        )
        """

        # Needs to execute AFTER binary_sensor creation!
        if camData["childDevices"] is None and (motionSensor or enableTimeSync):
            onvifDevice = await initOnvifEvents(hass, host, username, password)
            hass.data[DOMAIN][entry.entry_id]["eventsDevice"] = onvifDevice["device"]
            hass.data[DOMAIN][entry.entry_id]["onvifManagement"] = onvifDevice[
                "device_mgmt"
            ]
            if motionSensor:
                LOGGER.debug("Seting up motion sensor for the first time.")
                await setupOnvif(hass, entry)
            if enableTimeSync:
                await syncTime(hass, entry.entry_id)

        async def unsubscribe(event):
            if hass.data[DOMAIN][entry.entry_id]["events"]:
                await hass.data[DOMAIN][entry.entry_id]["events"].async_stop()

        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, unsubscribe)

    except Exception as e:
        LOGGER.error(
            "Unable to connect to Tapo: Cameras Control controller: %s", str(e)
        )
        raise ConfigEntryNotReady

    return True
