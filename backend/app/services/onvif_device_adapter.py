from app.core.security import decrypt_secret
from app.services.device_adapter import ResolvedStream, StreamPreference, StreamPurpose
from app.services.onvif_client import inject_uri_credentials


class OnvifDeviceAdapter:
    def resolve_stream(
        self,
        camera,
        purpose: StreamPurpose,
        *,
        preferred: StreamPreference = "auto",
    ) -> ResolvedStream:
        metadata = getattr(camera, "onvif_metadata", None)
        if metadata is None:
            raise ValueError("ONVIF metadata is missing; re-add or repair the camera")

        main_uri = str(metadata.recording_uri or "").strip()
        if not main_uri:
            raise ValueError("ONVIF recording profile has no stream URI")

        auxiliary_uri = (
            str(metadata.preview_uri or "").strip()
            if purpose == "preview"
            else str(metadata.detection_uri or "").strip()
        )
        auxiliary_token = (
            metadata.preview_profile_token
            if purpose == "preview"
            else metadata.detection_profile_token
        )
        recording_token = metadata.recording_profile_token

        if purpose == "recording" or preferred == "main":
            selected_uri = main_uri
            role = "main"
        elif preferred == "sub":
            if not auxiliary_uri or auxiliary_token == recording_token:
                raise ValueError("ONVIF sub stream is not available")
            selected_uri = auxiliary_uri
            role = "sub"
        elif auxiliary_uri:
            selected_uri = auxiliary_uri
            role = "sub" if auxiliary_token != recording_token else "main"
        else:
            selected_uri = main_uri
            role = "main"

        uri = inject_uri_credentials(
            selected_uri,
            str(camera.username),
            decrypt_secret(str(camera.password_encrypted)),
        )
        return ResolvedStream(uri=uri, role=role, purpose=purpose)
