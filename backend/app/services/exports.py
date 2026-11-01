"""CSV / Excel / PDF exports of jobs + application status."""
import csv
import io

COLUMNS = ["School", "District", "State", "Position", "Salary", "Posting Date", "Deadline", "Match Score",
           "J-1 Status", "Principal", "Principal Email", "Recruiter", "Recruiter Email", "Application URL",
           "Application Status", "Date Applied", "Follow-up Date", "Job Status", "Last Verified"]


def rows_for(jobs, apps_by_job) -> list[list]:
    out = []
    for j in jobs:
        principal = recruiter = None
        for l in sorted(j.contact_links, key=lambda l: {"HIGH": 0, "MEDIUM": 1}.get(l.confidence, 2)):
            c = l.contact
            if c.contact_type in ("PRINCIPAL", "ASSISTANT_PRINCIPAL") or l.relationship_type in ("SCHOOL_PRINCIPAL", "PRINCIPAL"):
                principal = principal or c
            elif c.contact_type not in ("PRINCIPAL",):
                recruiter = recruiter or c
        a = apps_by_job.get(j.id)

        def email(c):
            from .contacts import email_usable
            return c.email if c and email_usable(c) else ("" if not c else "No confirmed email")
        salary = j.salary_text or (f"${j.salary_min:,.0f}-${j.salary_max:,.0f}" if j.salary_min and j.salary_max
                                   else (f"up to ${j.salary_max:,.0f}" if j.salary_max else "Not published"))
        out.append([
            j.school.name if j.school else "", j.employer_name or "", j.state or "", j.job_title, salary,
            j.date_posted.isoformat() if j.date_posted else "", j.closing_text or (j.closing_date.isoformat() if j.closing_date else ""),
            j.match_score if j.match_score is not None else "", j.j1_status,
            (principal.full_name or principal.title) if principal else "", email(principal),
            (recruiter.full_name or recruiter.title) if recruiter else "", email(recruiter),
            j.application_url or j.official_job_url or "",
            a.application_status if a else "NOT_APPLIED",
            a.date_applied.isoformat() if a and a.date_applied else "",
            a.follow_up_date.isoformat() if a and a.follow_up_date else "",
            j.job_status, j.last_verified.strftime("%Y-%m-%d %H:%M") if j.last_verified else "",
        ])
    return out


def to_csv(rows) -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(COLUMNS)
    w.writerows(rows)
    return ("﻿" + buf.getvalue()).encode("utf-8")


def to_xlsx(rows) -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill
    from openpyxl.utils import get_column_letter
    wb = Workbook()
    ws = wb.active
    ws.title = "USA Job Hunter"
    ws.append(COLUMNS)
    for c in ws[1]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="1F3A5F")
    for r in rows:
        ws.append(r)
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions
    for i, col in enumerate(COLUMNS, 1):
        width = max([len(str(col))] + [len(str(r[i - 1])) for r in rows[:200]]) + 2
        ws.column_dimensions[get_column_letter(i)].width = min(width, 50)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def to_pdf(rows) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import landscape, legal
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=landscape(legal), leftMargin=18, rightMargin=18, topMargin=24, bottomMargin=18)
    styles = getSampleStyleSheet()
    small = styles["BodyText"].clone("small", fontSize=6.5, leading=8)
    keep = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 14, 15, 16]
    head = [Paragraph(f"<b>{COLUMNS[i]}</b>", small) for i in keep]
    data = [head] + [[Paragraph(str(r[i]).replace("&", "&amp;").replace("<", "&lt;"), small) for i in keep] for r in rows]
    t = Table(data, repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1F3A5F")), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#C8CED6")), ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F4F6F9")]),
    ]))
    doc.build([Paragraph("USA JOB HUNTER — Verified Mathematics Teaching Jobs", styles["Title"]), Spacer(1, 6), t])
    return buf.getvalue()
