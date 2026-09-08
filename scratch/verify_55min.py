import json

with open("schedule_schools.json", encoding="utf-8") as f:
    d = json.load(f)

all_ok = True
for s_id, s in d["schools"].items():
    print(f"\n=== {s['name']} ===")
    for p in s["periods"]:
        sh, sm = map(int, p["start"].split(":"))
        eh, em = map(int, p["end"].split(":"))
        dur = (eh * 60 + em) - (sh * 60 + sm)
        status = "OK (55 min)" if dur == 55 else f"DIFF ({dur} min)"
        if p["type"] == "aula":
            print(f"  [Aula]    {p['name']:<22} {p['start']} às {p['end']} -> {status}")
            if dur != 55:
                all_ok = False
        else:
            print(f"  [{p['type']:<7}] {p['name']:<22} {p['start']} às {p['end']} ({dur} min)")

print(f"\nResultado final: Todas as aulas de ambas as escolas têm exatamente 55 minutos? {'SIM ✅' if all_ok else 'NÃO ❌'}")
