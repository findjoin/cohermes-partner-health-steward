"""Health sidecar package.

Provides:
- A Unix-domain-socket-based service entrypoint.
- A tiny encrypted profile/state store.
- A structured JSON line protocol for health-state read/write requests.
"""

from .server import HealthSidecarServer, run_server
from .client import HealthSidecarClient, SidecarClientError
from .adapter import PartnerHealthAdapter, PartnerHealthAdapterError
from .ports import (
    ChannelSendAdapter,
    FileMemoryProjection,
    HealthStewardPorts,
    LLMAdapter,
    MemoryProjectionPort,
    NoopMemoryProjection,
    SourceFetchAdapter,
)
from .store import (
    Clock,
    FileKeyManager,
    Ed25519InboundMessageVerifier,
    HmacInboundMessageVerifier,
    InboundMessageVerifier,
    KeyManager,
    SystemClock,
)
from .profile import ProfileStoreError
from .sources import SourceLibrary, SourceLibraryError
from .operations import (
    JsonlOperationalAuditReader,
    JsonlOperatorAlertSink,
    OperationalAuditReader,
    OperationalMonitor,
    OperationalMonitorError,
    OperatorAlertSink,
    SyslogOperatorAlertSink,
    run_monitor_once,
)
from .weixin_delivery import (
    ChannelSendUncertainError,
    DeliveryResult,
    HermesWeixinTransport,
    WeixinHealthChannel,
    WeixinVersionMismatchError,
)
from .receipt_signer import (
    Ed25519ReceiptSigner,
    ReceiptSignerClient,
    ReceiptSignerError,
    ReceiptSignerServer,
)

__all__ = [
    "HealthSidecarServer",
    "run_server",
    "HealthSidecarClient",
    "SidecarClientError",
    "PartnerHealthAdapter",
    "PartnerHealthAdapterError",
    "HealthStewardPorts",
    "LLMAdapter",
    "SourceFetchAdapter",
    "ChannelSendAdapter",
    "MemoryProjectionPort",
    "FileMemoryProjection",
    "NoopMemoryProjection",
    "Clock",
    "KeyManager",
    "SystemClock",
    "FileKeyManager",
    "InboundMessageVerifier",
    "HmacInboundMessageVerifier",
    "Ed25519InboundMessageVerifier",
    "ProfileStoreError",
    "SourceLibrary",
    "SourceLibraryError",
    "OperationalAuditReader",
    "JsonlOperationalAuditReader",
    "JsonlOperatorAlertSink",
    "SyslogOperatorAlertSink",
    "OperationalMonitor",
    "OperationalMonitorError",
    "OperatorAlertSink",
    "run_monitor_once",
    "ChannelSendUncertainError",
    "DeliveryResult",
    "HermesWeixinTransport",
    "WeixinHealthChannel",
    "WeixinVersionMismatchError",
    "Ed25519ReceiptSigner",
    "ReceiptSignerClient",
    "ReceiptSignerError",
    "ReceiptSignerServer",
]
