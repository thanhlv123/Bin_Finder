"""Explicit authorized acquisition, independent of discovery and readiness."""
from bin_finder.acquisition.service import (
    AcquisitionCancelled, AcquisitionError, AcquisitionRequest,
    AcquisitionResult, AcquisitionService, verified_candidate_path,
)

__all__ = ["AcquisitionCancelled", "AcquisitionError", "AcquisitionRequest",
           "AcquisitionResult", "AcquisitionService", "verified_candidate_path"]
