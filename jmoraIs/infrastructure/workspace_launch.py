"""Append-only PostgreSQL adapter for the prospective launch boundary."""
from hashlib import sha256
from sqlalchemy import text
from jmoraIs.api.workspace_launch import (
    ClinicalWorkspaceLaunch, LaunchRejected, canonical_launch, launch_digest,
)
from jmoraIs.tenancy.context import current_tenant_context


class PostgreSQLClinicalWorkspaceLaunchRepository:
    def __init__(self, engine):
        if engine.dialect.name != 'postgresql':
            raise ValueError('PostgreSQL required')
        self._engine = engine

    def append(self, launch):
        tenant = current_tenant_context()
        if (launch.tenant_id, launch.organization_id, launch.principal_id) != (
            tenant.tenant_id, tenant.organization_id, tenant.principal_id):
            raise LaunchRejected('launch attribution rejected')
        with self._engine.begin() as connection:
            connection.execute(text('''INSERT INTO clinical_workspace_launches
                (launch_id,tenant_id,payload,integrity_hash,created_at)
                VALUES (:id,:tenant,:payload,:digest,:created)'''),
                dict(id=launch.launch_id, tenant=launch.tenant_id, payload=canonical_launch(launch),
                     digest=launch_digest(launch), created=launch.created_at))

    def get_exact(self, reference):
        tenant = current_tenant_context()
        if reference.tenant_id != tenant.tenant_id:
            raise LaunchRejected('launch unavailable')
        with self._engine.connect() as connection:
            row = connection.execute(text('''SELECT * FROM clinical_workspace_launches
                WHERE launch_id=:id AND tenant_id=:tenant'''),
                dict(id=reference.launch_id, tenant=tenant.tenant_id)).mappings().one_or_none()
            checkpoints = connection.execute(text('''SELECT stream_position,head_hash
                FROM cryptographic_stream_checkpoints
                WHERE stream_namespace='clinical_workspace_launches' AND stream_id=:id'''),
                dict(id=reference.launch_id)).all()
        launch = verify_launch_row(row, checkpoints)
        if reference.version != launch.version or reference.integrity_hash != launch_digest(launch):
            raise LaunchRejected('launch unavailable')
        return launch


def verify_launch_row(row, checkpoints):
    if row is None:
        raise LaunchRejected('launch unavailable')
    try:
        launch = ClinicalWorkspaceLaunch.model_validate_json(row['payload'])
        digest = sha256(row['payload'].encode('utf-8')).hexdigest()
        if (canonical_launch(launch) != row['payload'] or launch.launch_id != row['launch_id']
            or launch.tenant_id != row['tenant_id'] or launch.created_at != row['created_at']
            or digest != row['integrity_hash'] or len(checkpoints) != 1
            or tuple(checkpoints[0]) != (1, digest)):
            raise ValueError('invalid launch')
        return launch
    except Exception:
        raise LaunchRejected('launch integrity rejected') from None
