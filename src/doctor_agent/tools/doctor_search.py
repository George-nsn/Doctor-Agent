from __future__ import annotations

from typing import Any


DEFAULT_HOSPITALS_AND_DOCTORS: list[dict[str, Any]] = [
    {
        "hospital_name": "北京协和医院",
        "tier": "三级甲等",
        "city": "北京",
        "district": "东城区",
        "department": "消化内科",
        "doctors": [
            {
                "doctor_name": "李景南",
                "title": "主任医师",
                "specialties": ["急慢性胃炎", "胃食管反流", "消化性溃疡", "胃肠道出血"],
                "schedule": "周二上午、周四下午",
                "rating": 9.9,
            },
            {
                "doctor_name": "杨爱婷",
                "title": "副主任医师",
                "specialties": ["功能性消化不良", "胃痛", "幽门螺杆菌感染", "腹胀"],
                "schedule": "周一全天、周三上午",
                "rating": 9.8,
            },
        ],
    },
    {
        "hospital_name": "中日友好医院",
        "tier": "三级甲等",
        "city": "北京",
        "district": "朝阳区",
        "department": "消化内科",
        "doctors": [
            {
                "doctor_name": "杜时雨",
                "title": "主任医师",
                "specialties": ["萎缩性胃炎", "消化道早期病变", "胃痛及胃粘膜保护"],
                "schedule": "周一上午、周三下午",
                "rating": 9.7,
            }
        ],
    },
    {
        "hospital_name": "上海瑞金医院",
        "tier": "三级甲等",
        "city": "上海",
        "district": "黄浦区",
        "department": "消化内科",
        "doctors": [
            {
                "doctor_name": "邹多武",
                "title": "主任医师",
                "specialties": ["胃肠动力障碍", "急重症胃病", "消化内镜精准微创"],
                "schedule": "周二全天",
                "rating": 9.9,
            }
        ],
    },
    {
        "hospital_name": "复旦大学附属中山医院",
        "tier": "三级甲等",
        "city": "上海",
        "district": "徐汇区",
        "department": "心内科",
        "doctors": [
            {
                "doctor_name": "葛均波",
                "title": "主任医师",
                "specialties": ["冠心病", "心绞痛", "胸痛急危重症", "心肌梗死介入"],
                "schedule": "特需门诊预约",
                "rating": 10.0,
            }
        ],
    },
]


def search_doctors_and_hospitals(
    department: str = "消化内科",
    city: str | None = None,
    symptom_keyword: str | None = None,
    limit: int = 3,
) -> list[dict[str, Any]]:
    """Searches matching hospitals and certified doctors by department, location, and specialty symptoms."""
    department_norm = department.replace("科室", "").replace("专科", "").strip()
    results = []

    for item in DEFAULT_HOSPITALS_AND_DOCTORS:
        # Department match
        dept = item["department"]
        dept_match = (
            department_norm in dept
            or dept in department_norm
            or (("胃" in department_norm or "消化" in department_norm or "腹" in department_norm) and "消化" in dept)
            or (("胸" in department_norm or "心" in department_norm) and "心" in dept)
        )
        if not dept_match:
            continue

        # City match
        if city and city not in item["city"]:
            continue

        for doc in item["doctors"]:
            # Check specialty overlap
            specialty_hit = True
            if symptom_keyword:
                specialty_hit = any(symptom_keyword in s or s in symptom_keyword for s in doc["specialties"])

            results.append(
                {
                    "hospital": item["hospital_name"],
                    "hospital_tier": item["tier"],
                    "location": f"{item['city']} {item['district']}",
                    "department": item["department"],
                    "doctor_name": doc["doctor_name"],
                    "title": doc["title"],
                    "specialties": doc["specialties"],
                    "schedule": doc["schedule"],
                    "rating": doc["rating"],
                    "specialty_matched": specialty_hit,
                }
            )

    # Sort so symptom-matched specialties come first
    results.sort(key=lambda x: (x["specialty_matched"], x["rating"]), reverse=True)
    return results[:limit]
