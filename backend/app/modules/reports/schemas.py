"""Response shapes for reports."""

from datetime import date

from pydantic import BaseModel


class ColumnOut(BaseModel):
    key: str
    label: str
    kind: str


class TableOut(BaseModel):
    title: str
    columns: list[ColumnOut]
    # Values ready to show: numbers and amounts as strings, dates ISO, people/accounts as names.
    rows: list[dict[str, str | int | None]]


class ReportOut(BaseModel):
    key: str
    title: str
    start: date
    end: date
    sections: list[TableOut]


class ReportInfo(BaseModel):
    key: str
    title: str
    description: str


class RecordTypeInfo(BaseModel):
    key: str
    label: str
    columns: list[ColumnOut]
    statuses: list[str]


class ReportCatalogue(BaseModel):
    reports: list[ReportInfo]
    record_types: list[RecordTypeInfo]
    can_filter_by_rep: bool
