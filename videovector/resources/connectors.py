"""
VideoVector SDK Connectors Resource.

Provides methods for managing cloud storage connectors (GCS, S3, Azure).
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, BinaryIO, List, Optional, Union
from uuid import uuid4

from .._types import CloudFile, Connector, DeleteResponse, TestConnectionResult

if TYPE_CHECKING:
    from .._http import AsyncHttpClient, SyncHttpClient

_MAX_GCS_CREDENTIAL_BYTES = 64 * 1024


def _snapshot_gcs_credentials(
    credentials_file: Union[str, Path, BinaryIO],
) -> tuple[str, bytes, str]:
    """Read credential material exactly once into a bounded immutable payload."""
    if isinstance(credentials_file, (str, Path)):
        path = Path(credentials_file)
        filename = path.name
        with path.open("rb") as source:
            payload = source.read(_MAX_GCS_CREDENTIAL_BYTES + 1)
    else:
        filename = str(getattr(credentials_file, "name", "credentials.json"))
        original_position: Optional[int] = None
        try:
            original_position = credentials_file.tell()
        except (AttributeError, OSError):
            pass
        payload = credentials_file.read(_MAX_GCS_CREDENTIAL_BYTES + 1)
        if original_position is not None:
            try:
                credentials_file.seek(original_position)
            except (AttributeError, OSError):
                pass

    if not isinstance(payload, bytes):
        raise TypeError("credentials_file must be opened in binary mode")
    if not payload:
        raise ValueError("credentials_file must not be empty")
    if len(payload) > _MAX_GCS_CREDENTIAL_BYTES:
        raise ValueError("credentials_file cannot exceed 64 KiB")
    return (filename, payload, "application/json")


def _resolve_connector_idempotency_key(
    provider: str,
    idempotency_key: Optional[str],
) -> str:
    candidate = (idempotency_key or "").strip()
    if candidate:
        return candidate
    return f"connector-create-{provider}:{uuid4().hex}"


def _build_connector_json_body(
    base_fields: dict[str, object],
    export_base_path: Optional[str],
) -> dict[str, object]:
    body = dict(base_fields)
    if export_base_path:
        body["export_base_path"] = export_base_path
    return body


class ConnectorsResource:
    """
    Synchronous Connectors resource.

    Provides methods for managing cloud storage connectors that enable
    bulk import of videos from GCS, S3, or Azure Blob Storage.

    Example:
        client = VideoVector(api_key="<VIDEO_VECTOR_API_KEY>")

        # Create a GCS connector with service account credentials
        connector = client.connectors.create_gcs(
            name="Production GCS",
            bucket="my-videos-bucket",
            gcp_project_id="my-project-123",
            credentials_file="/path/to/service-account.json"
        )

        # Test the connection
        result = client.connectors.test(connector.connector_id)
        if result.success:
            print("Connection successful!")

        # Browse files in the bucket
        files = client.connectors.browse(
            connector.connector_id,
            prefix="videos/2024/",
            pattern="*.mp4"
        )
        for f in files:
            print(f"{f.name}: {f.size_bytes} bytes")

        # Create an S3 connector
        s3_connector = client.connectors.create_s3(
            name="AWS Videos",
            bucket="my-s3-bucket",
            region="us-east-1",
            aws_access_key_id="<AWS_ACCESS_KEY_ID>",
            aws_secret_access_key="..."
        )

        # Create an Azure connector
        azure_connector = client.connectors.create_azure(
            name="Azure Videos",
            storage_account="mystorageaccount",
            container="videos",
            tenant_id="...",
            client_id="...",
            client_secret="..."
        )
    """

    def __init__(self, client: "SyncHttpClient") -> None:
        self._client = client

    def create_gcs(
        self,
        *,
        name: str,
        bucket: str,
        gcp_project_id: str,
        credentials_file: Union[str, Path, BinaryIO],
        scopes: Optional[List[str]] = None,
        export_base_path: Optional[str] = None,
        import_mode: str = "all",
        idempotency_key: Optional[str] = None,
    ) -> Connector:
        """
        Create a Google Cloud Storage connector.

        Args:
            name: Connector name (1-100 characters)
            bucket: GCS bucket name
            gcp_project_id: GCP project ID
            credentials_file: Path to service account JSON file or file object

        Returns:
            Connector: Created GCS connector

        Raises:
            ValidationError: If parameters are invalid
            ExternalServiceError: If GCS connection fails
        """
        files: dict[str, tuple[str, bytes, str]] = {
            "credentials_file": _snapshot_gcs_credentials(credentials_file)
        }
        data: dict[str, Any] = {
            "name": name,
            "bucket": bucket,
            "gcp_project_id": gcp_project_id,
            "scopes": scopes or ["import"],
            "import_mode": import_mode,
        }
        if export_base_path:
            data["export_base_path"] = export_base_path
        response = self._client.post(
            "/connectors/gcs",
            files=files,
            data=data,
            idempotency_key=_resolve_connector_idempotency_key(
                "gcs",
                idempotency_key,
            ),
        )

        return Connector.model_validate(response)

    def create_s3(
        self,
        *,
        name: str,
        bucket: str,
        region: str,
        aws_access_key_id: str,
        aws_secret_access_key: str,
        scopes: Optional[List[str]] = None,
        export_base_path: Optional[str] = None,
        import_mode: str = "all",
        idempotency_key: Optional[str] = None,
    ) -> Connector:
        """
        Create an Amazon S3 connector.

        Args:
            name: Connector name (1-100 characters)
            bucket: S3 bucket name
            region: AWS region (e.g., "us-east-1")
            aws_access_key_id: AWS access key ID
            aws_secret_access_key: AWS secret access key

        Returns:
            Connector: Created S3 connector

        Raises:
            ValidationError: If parameters are invalid
            ExternalServiceError: If S3 connection fails
        """
        response = self._client.post(
            "/connectors/s3",
            json=_build_connector_json_body(
                {
                    "name": name,
                    "bucket": bucket,
                    "region": region,
                    "aws_access_key_id": aws_access_key_id,
                    "aws_secret_access_key": aws_secret_access_key,
                    "scopes": scopes or ["import"],
                    "import_mode": import_mode,
                },
                export_base_path,
            ),
            idempotency_key=_resolve_connector_idempotency_key("s3", idempotency_key),
        )
        return Connector.model_validate(response)

    def create_azure(
        self,
        *,
        name: str,
        storage_account: str,
        container: str,
        tenant_id: str,
        client_id: str,
        client_secret: str,
        scopes: Optional[List[str]] = None,
        export_base_path: Optional[str] = None,
        import_mode: str = "all",
        idempotency_key: Optional[str] = None,
    ) -> Connector:
        """
        Create an Azure Blob Storage connector.

        Args:
            name: Connector name (1-100 characters)
            storage_account: Azure storage account name
            container: Blob container name
            tenant_id: Azure AD tenant ID
            client_id: Azure AD application (client) ID
            client_secret: Azure AD client secret

        Returns:
            Connector: Created Azure connector

        Raises:
            ValidationError: If parameters are invalid
            ExternalServiceError: If Azure connection fails
        """
        response = self._client.post(
            "/connectors/azure",
            json=_build_connector_json_body(
                {
                    "name": name,
                    "storage_account": storage_account,
                    "container": container,
                    "tenant_id": tenant_id,
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "scopes": scopes or ["import"],
                    "import_mode": import_mode,
                },
                export_base_path,
            ),
            idempotency_key=_resolve_connector_idempotency_key("azure", idempotency_key),
        )
        return Connector.model_validate(response)

    def retrieve(self, connector_id: str) -> Connector:
        """
        Retrieve a connector by ID.

        Args:
            connector_id: Connector ID

        Returns:
            Connector: Connector details

        Raises:
            NotFoundError: If connector doesn't exist
        """
        response = self._client.get(f"/connectors/{connector_id}")
        return Connector.model_validate(response)

    def list(self) -> List[Connector]:
        """
        List all connectors.

        Returns:
            List[Connector]: All configured connectors
        """
        response = self._client.get("/connectors")
        return [Connector.model_validate(c) for c in response]

    def delete(self, connector_id: str) -> DeleteResponse:
        """
        Delete a connector.

        Note: This will not delete any videos already imported.

        Args:
            connector_id: Connector ID

        Returns:
            DeleteResponse: Confirmation message

        Raises:
            NotFoundError: If connector doesn't exist
            AuthorizationError: If admin scope is required
        """
        response = self._client.delete(f"/connectors/{connector_id}")
        return DeleteResponse.model_validate(response)

    def test(self, connector_id: str) -> TestConnectionResult:
        """
        Test a connector's connection to cloud storage.

        Verifies credentials and bucket/container access.

        Args:
            connector_id: Connector ID

        Returns:
            TestConnectionResult: Test result with success status

        Raises:
            NotFoundError: If connector doesn't exist
        """
        response = self._client.post(f"/connectors/{connector_id}/test")
        return TestConnectionResult.model_validate(response)

    def browse(
        self,
        connector_id: str,
        *,
        prefix: str = "",
        pattern: str = "*",
        recursive: bool = True,
    ) -> List[CloudFile]:
        """
        Browse files in the connected cloud storage.

        Args:
            connector_id: Connector ID
            prefix: Path prefix to filter files (e.g., "videos/2024/")
            pattern: Glob pattern for files (e.g., "*.mp4", "*.{mp4,mov}")
            recursive: Whether to scan subdirectories

        Returns:
            List[CloudFile]: Files matching the criteria

        Raises:
            NotFoundError: If connector doesn't exist
            ExternalServiceError: If browsing fails
        """
        response = self._client.post(
            f"/connectors/{connector_id}/browse",
            json={
                "prefix": prefix,
                "pattern": pattern,
                "recursive": recursive,
            },
        )
        return [CloudFile.model_validate(f) for f in response]


class AsyncConnectorsResource:
    """
    Asynchronous Connectors resource.

    Provides async methods for managing cloud storage connectors.

    Example:
        async with AsyncVideoVector(api_key="<VIDEO_VECTOR_API_KEY>") as client:
            # Create a GCS connector
            connector = await client.connectors.create_gcs(
                name="Production GCS",
                bucket="my-bucket",
                gcp_project_id="my-project",
                credentials_file="/path/to/creds.json"
            )

            # Test connection
            result = await client.connectors.test(connector.connector_id)

            # Browse files
            files = await client.connectors.browse(
                connector.connector_id,
                prefix="videos/"
            )
    """

    def __init__(self, client: "AsyncHttpClient") -> None:
        self._client = client

    async def create_gcs(
        self,
        *,
        name: str,
        bucket: str,
        gcp_project_id: str,
        credentials_file: Union[str, Path, BinaryIO],
        scopes: Optional[List[str]] = None,
        export_base_path: Optional[str] = None,
        import_mode: str = "all",
        idempotency_key: Optional[str] = None,
    ) -> Connector:
        """Create a Google Cloud Storage connector."""
        files: dict[str, tuple[str, bytes, str]] = {
            "credentials_file": _snapshot_gcs_credentials(credentials_file)
        }
        data: dict[str, Any] = {
            "name": name,
            "bucket": bucket,
            "gcp_project_id": gcp_project_id,
            "scopes": scopes or ["import"],
            "import_mode": import_mode,
        }
        if export_base_path:
            data["export_base_path"] = export_base_path
        response = await self._client.post(
            "/connectors/gcs",
            files=files,
            data=data,
            idempotency_key=_resolve_connector_idempotency_key(
                "gcs",
                idempotency_key,
            ),
        )

        return Connector.model_validate(response)

    async def create_s3(
        self,
        *,
        name: str,
        bucket: str,
        region: str,
        aws_access_key_id: str,
        aws_secret_access_key: str,
        scopes: Optional[List[str]] = None,
        export_base_path: Optional[str] = None,
        import_mode: str = "all",
        idempotency_key: Optional[str] = None,
    ) -> Connector:
        """Create an Amazon S3 connector."""
        response = await self._client.post(
            "/connectors/s3",
            json=_build_connector_json_body(
                {
                    "name": name,
                    "bucket": bucket,
                    "region": region,
                    "aws_access_key_id": aws_access_key_id,
                    "aws_secret_access_key": aws_secret_access_key,
                    "scopes": scopes or ["import"],
                    "import_mode": import_mode,
                },
                export_base_path,
            ),
            idempotency_key=_resolve_connector_idempotency_key("s3", idempotency_key),
        )
        return Connector.model_validate(response)

    async def create_azure(
        self,
        *,
        name: str,
        storage_account: str,
        container: str,
        tenant_id: str,
        client_id: str,
        client_secret: str,
        scopes: Optional[List[str]] = None,
        export_base_path: Optional[str] = None,
        import_mode: str = "all",
        idempotency_key: Optional[str] = None,
    ) -> Connector:
        """Create an Azure Blob Storage connector."""
        response = await self._client.post(
            "/connectors/azure",
            json=_build_connector_json_body(
                {
                    "name": name,
                    "storage_account": storage_account,
                    "container": container,
                    "tenant_id": tenant_id,
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "scopes": scopes or ["import"],
                    "import_mode": import_mode,
                },
                export_base_path,
            ),
            idempotency_key=_resolve_connector_idempotency_key("azure", idempotency_key),
        )
        return Connector.model_validate(response)

    async def retrieve(self, connector_id: str) -> Connector:
        """Retrieve a connector by ID."""
        response = await self._client.get(f"/connectors/{connector_id}")
        return Connector.model_validate(response)

    async def list(self) -> List[Connector]:
        """List all connectors."""
        response = await self._client.get("/connectors")
        return [Connector.model_validate(c) for c in response]

    async def delete(self, connector_id: str) -> DeleteResponse:
        """Delete a connector."""
        response = await self._client.delete(f"/connectors/{connector_id}")
        return DeleteResponse.model_validate(response)

    async def test(self, connector_id: str) -> TestConnectionResult:
        """Test a connector's connection to cloud storage."""
        response = await self._client.post(f"/connectors/{connector_id}/test")
        return TestConnectionResult.model_validate(response)

    async def browse(
        self,
        connector_id: str,
        *,
        prefix: str = "",
        pattern: str = "*",
        recursive: bool = True,
    ) -> List[CloudFile]:
        """Browse files in the connected cloud storage."""
        response = await self._client.post(
            f"/connectors/{connector_id}/browse",
            json={
                "prefix": prefix,
                "pattern": pattern,
                "recursive": recursive,
            },
        )
        return [CloudFile.model_validate(f) for f in response]
