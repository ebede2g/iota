import os
import math
from datetime import datetime, timedelta

# Параметри
pathToCalFolder = "/home/mykhailo/.var/lib/radicale/collections/collection-root/" # закінечння на /
BASE_CAL_FOLDER = "/home/mykhailo/.var/lib/radicale/collections/collection-root/"

wsh = 8         # початок робочих годин
weh = 22        # кінець
wd = weh - wsh  # тривалість робочого дня = 14
rd = 24 - wd    # час поза роботою = 10
koef = 24 / wd  # коефіцієнт масштабу часу

# Шаблон VTODO
form = """BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//MyApp//EN
BEGIN:VTODO
DESCRIPTION:
DTSTAMP;X-VOBJ-FLOATINGTIME-ALLOWED=TRUE:{time}
DTSTART:{time}
DUE:{due_time}
STATUS:NEEDS-ACTION
SUMMARY:{label}
UID:{time}.ics
END:VTODO
END:VCALENDAR"""


def gdl(sp, ep):  # генерує межі робочих днів
    days = []
    current_day = sp
    while current_day < ep + timedelta(days=3):
        end_of_day = current_day.replace(hour=weh, minute=0, second=0, microsecond=0)
        days.append(end_of_day)
        current_day += timedelta(days=1)
    return days


def atwh(dt_arr):  # підганяє під робочі години
    now = datetime.now()
    op_dt_arr = []
    sp = dt_arr[0]
    if sp.hour >= weh or sp.hour < wsh:
        next_morning = sp.replace(hour=wsh, minute=sp.minute, second=sp.second)
        if sp.hour >= weh:
            next_morning += timedelta(days=1)
        hours_to_add = next_morning - sp
        for dt in dt_arr:
            op_dt_arr.append(dt + hours_to_add)
        sp = op_dt_arr[0]
    else:
        op_dt_arr = dt_arr

    ep = sp + timedelta(days=((op_dt_arr[-1] - op_dt_arr[0]).days) * koef)

    ans = []
    for gdl_dt in gdl(sp, ep):
        next_temp_dt_arr = []
        for dt in op_dt_arr:
            if dt < gdl_dt:
                ans.append(dt)
            else:
                next_temp_dt_arr.append(dt + timedelta(hours=rd))
        op_dt_arr = next_temp_dt_arr
    return ans


def gfdt(n, j):  # генерує n таймштампів
    now = datetime.now()
    dt_arr = []
    j_h = math.pow(j, 1 / (24 * 60))

    if j == 1:
        for i in range(30):
            ft = now + timedelta(days=i / koef, minutes=30)
            dt_arr.append(ft)
    elif j > 1:
        for i in range(n * 24 * 60):
            if not i % (24 * 60):
                unit_days = math.pow(j_h, i)
                td = timedelta(minutes=30 + unit_days * 24 * 60 - 1440 - 7*24*60)
                ft = now + td
                dt_arr.append(ft)
    else:
        dt_arr.append(now + timedelta(minutes=30))

    return dt_arr[:n]  # обмежити довжину списку до n








def write(label, UserCal, n, j):
    pathToCalFolder = os.path.join(BASE_CAL_FOLDER, UserCal)  # використовуємо глобальну константу базової папки
    print(pathToCalFolder)
    if not os.path.exists(pathToCalFolder):
        os.makedirs(pathToCalFolder)

    dt_arr = atwh(gfdt(n, j))
    for dt in dt_arr:
        print("  >>", dt.strftime("%Y-%m-%d %H:%M:%S"))
    for dt in dt_arr:
        time_str = dt.strftime("%Y%m%dT%H%M%S")
        due_dt = dt + timedelta(minutes=5)
        due_time_str = due_dt.strftime("%Y%m%dT%H%M%S")

        ics_content = form.format(time=time_str, due_time=due_time_str, label=label)

        filename = f"{time_str}.ics"
        filepath = os.path.join(pathToCalFolder, filename)
        with open(filepath, "w", encoding="utf-8") as file:
            file.write(ics_content)
        print(f"Файл створено: {filepath}")


