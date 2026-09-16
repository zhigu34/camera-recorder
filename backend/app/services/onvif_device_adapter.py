from app.core.security import decrypt_secret
from app.services.device_adapter import ResolvedStream
from app.services.media_source import MediaSource, StreamPreference, StreamPurpose
from app.services.onvif_client import inject_uri_credentials


class OnvifDeviceAdapter:
    def resolve_media_source(
        self,
        camera,
        purpose: StreamPurpose,
        *,
        preferred: StreamPreference = "auto",
    ) -> MediaSource:
        connection = getattr(camera, "connection", None)
        if connection is not None:
            if str(connection.adapter) != "onvif":
                raise ValueError(
                    f"current connection adapter is {connection.adapter}, expected onvif"
                )
            metadata = getattr(connection, "onvif_config", None)
            if metadata is None:
                raise ValueError("ONVIF current connection config is missing")
            username = str(connection.username)
            password_encrypted = str(connection.password_encrypted)
        else:
            metadata = getattr(camera, "onvif_metadata", None)
            if metadata is None:
                raise ValueError("ONVIF metadata is missing; re-add or repair the camera")
            username = str(camera.username)
            password_encrypted = str(camera.password_encrypted)

        main_uri = str(getattr(metadata, "recording_uri", None) or "").strip()
        if not main_uri:
            raise ValueError("ONVIF recording profile has no stream URI")

        auxiliary_uri = (
            str(getattr(metadata, "preview_uri", None) or "").strip()
            if purpose == "preview"
            else str(getattr(metadata, "detection_uri", None) or "").strip()
        )
        recording_token = getattr(metadata, "recording_profile_token", None)
        auxiliary_token = (
            getattr(metadata, "preview_profile_token", None)
            if purpose == "preview"
            else getattr(metadata, "detection_profile_token", None)
        )
        auxiliary_is_sub = bool(
            auxiliary_uri
            and (
                auxiliary_token != recording_token
                if auxiliary_token is not None or recording_token is not None
                else auxiliary_uri != main_uri
            )
        )

        if purpose == "recording" or preferred == "main":
            selected_uri = main_uri
            role = "main"
        elif preferred == "sub":
            if not auxiliary_is_sub:
                raise ValueError("ONVIF sub stream is not available")
            selected_uri = auxiliary_uri
            role = "sub"
        elif auxiliary_uri:
            selected_uri = auxiliary_uri
            role = "sub" if auxiliary_is_sub else "main"
        else:
            selected_uri = main_uri
            role = "main"

        uri = inject_uri_credentials(
            selected_uri,
            username,
            decrypt_secret(password_encrypted),
        )
        return MediaSource(
            adapter="onvif",
            transport="rtsp",
            uri=uri,
            role=role,
            purpose=purpose,
        )

    def resolve_stream(
        self,
        camera,
        purpose: StreamPurpose,
        *,
        preferred: StreamPreference = "auto",
    ) -> ResolvedStream:
        source = self.resolve_media_source(camera, purpose, preferred=preferred)
        assert source.uri is not None
        return ResolvedStream(uri=source.uri, role=source.role, purpose=source.purpose)


OnvifMediaAdapter = OnvifDeviceAdapter
