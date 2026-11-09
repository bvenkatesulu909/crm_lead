"""Pages shaped like the AP RERA approved-project search (ADR 0019, Amendment A).

The STRUCTURE copies the real site as seen on 2026-11-09 (the form ``HomeForm`` and its hidden
fields, the results table ``ContentPlaceHolder1_gvApprovedProject`` with its seven columns, the "No
Data found" message). The CONTENT is invented: no real project, promoter or number is kept in the
repository."""

HEADER = (
    '<thead><tr><th scope="col">S.No.</th><th scope="col">Application No</th>'
    '<th scope="col">Registration No</th><th scope="col">Project Name</th>'
    '<th scope="col">Promoter Name</th><th scope="col">Place</th><th scope="col">Status</th>'
    "</tr></thead>"
)
NUMBER = "P00000000042"  # invented


def row(
    n: int,
    number: str = NUMBER,
    project: str = "Eval Towers Phase 1",
    promoter: str = "Eval Builders Pvt Ltd",
    place: str = "Anantapuramu",
    status: str = "APRERA Registered",
) -> str:
    def cell(css: str, ident: str, text: str) -> str:
        return (
            f'<td class="{css}"><span id="ContentPlaceHolder1_gvApprovedProject_{ident}_{n}">'
            f"{text}</span></td>"
        )

    return (
        f'<tr><td class="textcenter">{n}</td>'
        + cell("textcenter", "lblRegistrationID", f"APP{n:05d}")
        + cell("textcenter", "lblRegistrationNo", number)
        + cell("textleft", "lblProjectName", project)[:-5]
        + f'<input type="hidden" name="ctl00$x$ctl0{n}$hdnAppStatus" value="23" /></td>'
        + cell("textleft", "lblPromoter", promoter)
        + cell("textleft", "lblPlace", place)
        + cell("textleft", "lblStatus", status)
        + "</tr>"
    )


SCRIPT = (
    "<script>function BindEvents(){ var t = $('#ContentPlaceHolder1_gvApprovedProject')"
    ".DataTable({}); }</script>"
)


def results(*rows: str, header: str = HEADER, extra: str = "") -> str:
    body = "".join(rows) or row(1)
    return (
        f'<html><head>{SCRIPT}</head><body><form method="post" '
        f'action="./ApprovedProjectSearch.aspx" id="HomeForm">'
        f'<table cellspacing="1" rules="all" class="table table-striped grid_div" border="1" '
        f'id="ContentPlaceHolder1_gvApprovedProject">{header}<tbody>{body}</tbody></table>'
        f"{extra}</form></body></html>"
    )


NONE = (
    f'<html><head>{SCRIPT}</head><body><form method="post" '
    'action="./ApprovedProjectSearch.aspx" id="HomeForm">'
    '<div id="ContentPlaceHolder1_divNoDate" class="row innerdivrow"><div class="col-xs-12">'
    '<span id="ContentPlaceHolder1_Label1" style="color:Red;">No Data found on your entered text'
    "</span></div></div></form></body></html>"
)

HIDDEN = {
    "__EVENTTARGET": "",
    "__EVENTARGUMENT": "",
    "__VIEWSTATE": "dDwtMTI3OTMzNDM4NDs7Pg==",
    "__VIEWSTATEGENERATOR": "4F1E2A07",
    "__SCROLLPOSITIONX": "0",
    "__SCROLLPOSITIONY": "0",
    "__VIEWSTATEENCRYPTED": "",
    "__EVENTVALIDATION": "/wEdAAUAAAD/////AQAAAAAAAAAPAQAAAA==",
    # Sorting helpers of the real page: NOT on the allow-list, so they are never sent.
    "ctl00$ContentPlaceHolder1$hdcolumn": "",
    "ctl00$ContentPlaceHolder1$hdndtm": "",
    "ctl00$ContentPlaceHolder1$hdclass": "",
}

SEARCH = (
    "<html><body>"
    '<form method="post" action="./ApprovedProjectSearch.aspx" id="HomeForm">'
    + "".join(
        f'<input type="hidden" name="{name}" id="{name}" value="{value}" />'
        for name, value in HIDDEN.items()
    )
    + '<form role="form"><input type="text" class="form-control input-sm" placeholder="First Name">'
    "</form>"
    '<input name="ctl00$ContentPlaceHolder1$txtName" type="text" id="ContentPlaceHolder1_txtName" '
    'placeholder="Enter Key Word" />'
    '<input type="submit" name="ctl00$ContentPlaceHolder1$btnSubmit" value="Search" '
    'id="ContentPlaceHolder1_btnSubmit" />'
    "</form></body></html>"
)
