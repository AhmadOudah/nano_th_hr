import frappe
from frappe.utils import get_first_day, get_last_day, flt

@frappe.whitelist()
def build_department_distribution(department, month):
    """
    month format: '2025-10'
    يبني سجل Department Revenue Distribution واحد شهريًا للقسم المحدد
    ويقرأ:
      - إيراد القسم من فواتير Healthcare
      - الحضور والمناوبات لكل موظف في القسم
    ثم يملأ Child Table بعناصر الموظفين ويحسب final_share بالتطبيع.
    """
    # 1) حدد نطاق التاريخ
    start_date = f"{month}-01"
    end_date = str(get_last_day(start_date))

    # 2) جلب أو إنشاء السجل
    name = frappe.db.get_value("Department Revenue Distribution",
                               {"department": department, "fiscal_month": month}, "name")
    if name:
        doc = frappe.get_doc("Department Revenue Distribution", name)
        doc.revenue_distribution_items = []
    else:
        doc = frappe.new_doc("Department Revenue Distribution")
        doc.fiscal_month = month
        doc.department = department

    # 3) احسب إيراد القسم من فواتير النظام الطبي
    total_rev = _get_healthcare_department_revenue(department, start_date, end_date)
    doc.total_department_revenue = total_rev
    # مبدئيًا خلي الـ pool = 30% من الإيراد (تقدر تغيّرها من إعدادات لاحقًا)
    doc.allocated_pool = flt(total_rev) * 0.30

    # 4) الموظفون النشطون في هذا القسم
    employees = frappe.get_all("Employee", 
                               filters={"department": department, "status": "Active"},
                               fields=["name"])

    # 5) كوّن الأوزان لكل موظف بناء على الحضور والمناوبات
    total_weight = 0.0
    rows = []
    for e in employees:
        present_days = _count_present_days(e["name"], start_date, end_date)
        shifts_count = _count_shifts(e["name"], start_date, end_date)

        # وزن بسيط: (أيام الحضور * 1) + (عدد المناوبات * 0.5)
        performance_weight = present_days * 1.0 + shifts_count * 0.5
        total_weight += performance_weight

        rows.append({
            "employee": e["name"],
            "present_days": present_days,
            "shifts_count": shifts_count,
            "performance_weight": performance_weight,
        })

    # 6) التطبيع وتعبئة الجدول
    for r in rows:
        base_share = 0
        final_share = 0
        if total_weight > 0:
            base_share = (r["performance_weight"] / total_weight) * doc.allocated_pool
            final_share = base_share
        doc.append("revenue_distribution_items", {
            "employee": r["employee"],
            "present_days": r["present_days"],
            "shifts_count": r["shifts_count"],
            "performance_weight": r["performance_weight"],
            "base_share": base_share,
            "final_share": final_share,
            "notes": ""
        })

    doc.save(ignore_permissions=True)
    return {"name": doc.name, "total_department_revenue": total_rev, "allocated_pool": doc.allocated_pool}

def _get_healthcare_department_revenue(dept, start_date, end_date):
    """
    يسحب إيرادات القسم من فواتير Healthcare.
    إذا كنت تستخدم Doctype: Healthcare Service Invoice أو Sales Invoice مع cost_center per dept
    عدّل الاستعلام حسب بيئتك.
    """
    # مثال عند الاعتماد على Sales Invoice + Cost Center للقسم
    res = frappe.db.sql("""
        SELECT SUM(grand_total)
        FROM `tabSales Invoice`
        WHERE docstatus=1
          AND posting_date BETWEEN %s AND %s
          AND cost_center IN (
            SELECT name FROM `tabCost Center` WHERE department = %s
          )
    """, (start_date, end_date, dept))
    return flt(res[0][0]) if res and res[0][0] else 0.0

def _count_present_days(employee, start_date, end_date):
    cnt = frappe.db.count("Attendance", {
        "employee": employee,
        "status": "Present",
        "attendance_date": ["between", [start_date, end_date]]
    })
    return cnt or 0

def _count_shifts(employee, start_date, end_date):
    cnt = frappe.db.count("Shift Assignment", {
        "employee": employee,
        "start_date": ["between", [start_date, end_date]]
    })
    return cnt or 0
