#!/usr/bin/env python3
"""Dumps the live schema (tables, columns, PK, FK, counts) to build/schema_info.json"""
import json, os, psycopg2
con = psycopg2.connect(host="127.0.0.1", user="postgres", dbname="raktasetu"); cur = con.cursor()
ORDER = ["department", "blood_group", "blood_compatibility", "venue", "blood_bank", "hospital", "deferral_reason", "sponsor",
         "member", "donor", "event", "blood_drive", "event_volunteer", "event_sponsor", "registration", "screening", "donation",
         "blood_request", "request_pledge", "notification", "donor_reminder", "activity_log"]
info = {"tables": []}
for t in ORDER:
    cur.execute("""SELECT column_name, data_type, character_maximum_length, numeric_precision, numeric_scale, is_nullable, column_default
                   FROM information_schema.columns WHERE table_schema='public' AND table_name=%s ORDER BY ordinal_position""", (t,))
    cols = [dict(name=c[0], type=c[1], len=c[2], prec=c[3], scale=c[4], nullable=c[5] == "YES", default=c[6]) for c in cur.fetchall()]
    cur.execute("""SELECT a.attname FROM pg_index i JOIN pg_attribute a ON a.attrelid=i.indrelid AND a.attnum = ANY(i.indkey)
                   WHERE i.indrelid=%s::regclass AND i.indisprimary ORDER BY array_position(i.indkey, a.attnum)""", (t,))
    pk = [r[0] for r in cur.fetchall()]
    cur.execute("""SELECT con.conname, array_agg(a.attname ORDER BY k.ord), cl.relname, array_agg(fa.attname ORDER BY k.ord)
                   FROM pg_constraint con
                   JOIN LATERAL unnest(con.conkey, con.confkey) WITH ORDINALITY AS k(att, fatt, ord) ON true
                   JOIN pg_attribute a ON a.attrelid = con.conrelid AND a.attnum = k.att
                   JOIN pg_attribute fa ON fa.attrelid = con.confrelid AND fa.attnum = k.fatt
                   JOIN pg_class cl ON cl.oid = con.confrelid
                   WHERE con.contype='f' AND con.conrelid=%s::regclass GROUP BY con.conname, cl.relname ORDER BY min(k.att)""", (t,))
    fks = [dict(name=r[0], cols=r[1], ref=r[2], refcols=r[3]) for r in cur.fetchall()]
    cur.execute(f"SELECT count(*) FROM {t}"); n = cur.fetchone()[0]
    info["tables"].append(dict(name=t, columns=cols, pk=pk, fks=fks, rows=n))
q = lambda s: (cur.execute(s), cur.fetchone()[0])[1]
info["counts"] = dict(
    tables=q("select count(*) from information_schema.tables where table_schema='public' and table_type='BASE TABLE'"),
    views=q("select count(*) from information_schema.views where table_schema='public'"),
    pk=q("select count(*) from pg_constraint c join pg_namespace n on n.oid=c.connamespace where n.nspname='public' and contype='p'"),
    fk=q("select count(*) from pg_constraint c join pg_namespace n on n.oid=c.connamespace where n.nspname='public' and contype='f'"),
    unique=q("select count(*) from pg_constraint c join pg_namespace n on n.oid=c.connamespace where n.nspname='public' and contype='u'"),
    check=q("select count(*) from pg_constraint c join pg_namespace n on n.oid=c.connamespace where n.nspname='public' and contype='c'"),
    exclusion=q("select count(*) from pg_constraint c join pg_namespace n on n.oid=c.connamespace where n.nspname='public' and contype='x'"),
    functions=q("select count(*) from pg_proc p join pg_namespace n on n.oid=p.pronamespace where n.nspname='public' and p.prokind='f' and p.prorettype <> 'trigger'::regtype and not exists (select 1 from pg_depend d where d.objid=p.oid and d.deptype='e')"),
    trigger_functions=q("select count(*) from pg_proc p join pg_namespace n on n.oid=p.pronamespace where n.nspname='public' and p.prorettype = 'trigger'::regtype and not exists (select 1 from pg_depend d where d.objid=p.oid and d.deptype='e')"),
    triggers=q("select count(*) from pg_trigger where not tgisinternal"),
    indexes=q("select count(*) from pg_indexes where schemaname='public'"),
    partial_unique=q("select count(*) from pg_indexes where schemaname='public' and indexdef ilike '%WHERE%'"),
)
json.dump(info, open(os.path.join(os.path.dirname(__file__), "schema_info.json"), "w"), indent=1, default=str)
print(info["counts"]); print({t["name"]: t["rows"] for t in info["tables"]})
