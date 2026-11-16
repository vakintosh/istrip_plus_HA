"""Configuration permission for the unverified sound-reactive protocol."""

import logging

import voluptuous as vol
from homeassistant.config_entries import ConfigFlowResult, OptionsFlow

_LOGGER = logging.getLogger(__name__)


class IstripOptionsFlow(OptionsFlow):
    """Edit the existing settings without reloading or starting music."""

    async def async_step_init(self, user_input=None) -> ConfigFlowResult:
        runtime = getattr(self.config_entry, "runtime_data", None)
        light = runtime.get("light") if isinstance(runtime, dict) else None
        if light is None:
            return self.async_abort(reason="not_loaded")

        errors = {}
        if user_input is not None:
            allowed = user_input.get("experimental_music")
            if type(allowed) is not bool:
                errors["base"] = "invalid_permission"
            else:
                try:
                    if allowed != light.settings.experimental_music or (
                        not allowed and light._music_active
                    ):
                        await light.async_set_control("experimental_music", allowed)
                except Exception:  # noqa: BLE001 - retain the form on save/BLE failure
                    _LOGGER.exception("Could not update sound-reactive permission")
                    errors["base"] = "cannot_update"
                else:
                    # Store already owns settings and the recovery journal;
                    # avoid a second source of truth in entry.options.
                    return self.async_create_entry(
                        title="", data=dict(self.config_entry.options)
                    )

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        "experimental_music", default=light.settings.experimental_music
                    ): bool
                }
            ),
            errors=errors,
        )
