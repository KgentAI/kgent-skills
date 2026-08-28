class KgentError(Exception):
    exit_code = 1


class ConfigError(KgentError):
    exit_code = 1


class VersionConflict(KgentError):
    exit_code = 4

    def __init__(self, doc_uri: str = "", expected: str = "", found: str = ""):
        super().__init__(f"VersionConflict on {doc_uri}: expected {expected}, found {found}")
        self.expected = expected
        self.found = found


class PolicyError(KgentError):
    exit_code = 3


class ApprovalRequired(PolicyError):
    pass


class ApprovalBindingMismatch(PolicyError):
    pass


class PartialFailure(KgentError):
    exit_code = 2
