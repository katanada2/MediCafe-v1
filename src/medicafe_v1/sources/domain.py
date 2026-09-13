from dataclasses import dataclass


class CommandError(Exception):
    def __init__(self, reason_code):
        self.reason_code = reason_code
        super().__init__(reason_code)


@dataclass(frozen=True)
class CommandResult:
    reason_code: str
    delivery_id: object | None = None
    parse_result_id: object | None = None
    decision_id: object | None = None
    patient_id: object | None = None
    encounter_id: object | None = None
