"""Validation result structures shared by the engine, UI, and tests."""

from dataclasses import asdict, dataclass, field
from typing import Any, Literal


Severity = Literal["DATA_ERROR", "WARNING", "IGNORED"]


@dataclass(frozen=True)
class ValidationIssue:
    """Represent one locatable and explainable validation outcome."""

    severity: Severity
    code: str
    sheet: str
    row: int | None
    field: str
    error_value: Any
    message: str
    fix: str

    def to_dict(self) -> dict[str, Any]:
        """Convert the issue to a UI/export dictionary."""

        return asdict(self)


@dataclass
class ValidationReport:
    """Collect errors, warnings, and ignored records and expose a summary."""

    issues: list[ValidationIssue] = field(default_factory=list)

    def add(self, issue: ValidationIssue) -> None:
        """Add one validation outcome."""

        self.issues.append(issue)

    @property
    def data_errors(self) -> list[ValidationIssue]:
        """Return blocking data errors."""

        return [issue for issue in self.issues if issue.severity == "DATA_ERROR"]

    @property
    def warnings(self) -> list[ValidationIssue]:
        """Return non-blocking warnings."""

        return [issue for issue in self.issues if issue.severity == "WARNING"]

    @property
    def ignored(self) -> list[ValidationIssue]:
        """Return excluded records that require summary."""

        return [issue for issue in self.issues if issue.severity == "IGNORED"]

    @property
    def is_valid(self) -> bool:
        """Return True when no Data Error exists."""

        return not self.data_errors

    def summary(self) -> dict[str, int | bool]:
        """Build counts suitable for the UI."""

        return {
            "is_valid": self.is_valid,
            "data_error_count": len(self.data_errors),
            "warning_count": len(self.warnings),
            "ignored_count": len(self.ignored),
            "total_issue_count": len(self.issues),
        }
