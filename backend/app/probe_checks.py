"""Pure live-probe verdicts, independent of provider calls and DB initialization."""
import re


def speech_terms(text, expected):
    normalized = re.sub(r'[^\w]+', ' ', text.casefold())
    return bool(expected) and all(term.casefold() in normalized for term in expected)


def exit_status(report):
    if report.get('stopped') or any(value is False for value in report['checks'].values()):
        return 1
    if any(value is not True for value in report['checks'].values()):
        return 2  # Incomplete, never advertised as successful verification.
    return 0 if report['checks'] else 2
