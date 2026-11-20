"""R27: cifra el documento de identidad en toda la base.

Desde la carpeta back/:
    python scripts/migrar_documentos_r27.py              simulación: muestra todo y NO guarda
    python scripts/migrar_documentos_r27.py --aplicar    hace el cambio y lo guarda
    python scripts/migrar_documentos_r27.py --verificar  comprueba el resultado

Qué hace (todo en UNA transacción: si algo falla, no queda nada a medias):
  1. Crea la tabla `identidades` (bóveda) si no existe.
  2. Para cada documento de pacientes y usuarios calcula su número interno
     (core/identidad.py) y guarda el documento cifrado en la bóveda.
  3. Quita las llaves foráneas que apuntan a pacientes/usuarios, cambia el
     documento por el número interno en todas las columnas que lo usan y vuelve
     a crear las llaves foráneas (la base comprueba que nada quedó suelto).
  4. Deja un registro en la auditoría.

No toca auditoria_cambios: cambiar registros viejos rompería la cadena de R28.
Por eso esa tabla deja de tener llave foránea hacia usuarios (la auditoría es un
registro inmutable y debe poder guardar el actor original).

Requiere CIFRADO_LLAVE_K1 en pass.env. Correrlo dos veces no hace daño: si ya
no quedan documentos en claro, no cambia nada.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import psycopg2
from psycopg2.extras import Json

from core.cifrado import cifrar, descifrar
from core.config import PG_CONNECTION_STRING
from core.identidad import CONTEXTO, es_interno, interno

PK = {"pacientes": "numero_documento_paciente", "usuarios": "numero_documento_usuario"}
EXCLUIDAS = {"auditoria_cambios", "identidades"}

# Columnas sin llave foránea que también guardan el documento de una persona.
CANDIDATAS = {
    "numero_documento_usuario", "numero_documento_paciente", "id_paciente", "paciente_id",
    "deleted_by", "registrado_por", "creado_por", "solicitado_por", "revisado_por",
    "remitido_por", "registrado_resultado_por", "reconocida_por", "realizado_por",
    "prescrito_por", "especialista_asignado", "enviado_por", "clasificado_por",
    "medico_responsable", "medico_remitente", "especialista_destino", "aprobado_por",
    "rechazado_por", "desbloqueado_por", "bloqueado_por", "medico_id", "especialista_id",
    "usuario_id",
}

DDL = open(Path(__file__).resolve().parent.parent / "migrations" / "019_identidad_cifrada_r27.sql",
           encoding="utf-8").read().replace("BEGIN;", "").replace("COMMIT;", "")


def llaves_foraneas(cur):
    """Todas las llaves foráneas del esquema, con sus columnas de ambos lados."""
    cur.execute("""
        SELECT con.conname, cl.relname,
               ARRAY(SELECT a.attname FROM unnest(con.conkey) k
                     JOIN pg_attribute a ON a.attrelid = con.conrelid AND a.attnum = k),
               ref.relname,
               ARRAY(SELECT a.attname FROM unnest(con.confkey) k
                     JOIN pg_attribute a ON a.attrelid = con.confrelid AND a.attnum = k),
               pg_get_constraintdef(con.oid)
        FROM pg_constraint con
        JOIN pg_class cl ON cl.oid = con.conrelid
        JOIN pg_namespace n ON n.oid = cl.relnamespace
        JOIN pg_class ref ON ref.oid = con.confrelid
        WHERE con.contype = 'f' AND n.nspname = 'public';
    """)
    return [{"nombre": nombre, "tabla": tabla, "columnas": list(cols), "ref": ref,
             "ref_columnas": list(ref_cols), "def": definicion}
            for nombre, tabla, cols, ref, ref_cols, definicion in cur.fetchall()]


def toca(fk, columnas) -> bool:
    """La llave foránea usa (de cualquier lado) alguna columna que cambia."""
    return (any((fk["tabla"], c) in columnas for c in fk["columnas"])
            or any((fk["ref"], c) in columnas for c in fk["ref_columnas"])
            or (fk["tabla"] in EXCLUIDAS and fk["ref"] in PK))


def columnas_con_documento(cur, fks):
    cols = {(t, c) for t, c in PK.items()}
    for f in fks:
        if f["ref"] in PK and f["tabla"] not in EXCLUIDAS:
            cols |= {(f["tabla"], c) for c, rc in zip(f["columnas"], f["ref_columnas"]) if rc == PK[f["ref"]]}
    cur.execute("""
        SELECT table_name, column_name FROM information_schema.columns
        WHERE table_schema = 'public' AND data_type = 'bigint'
          AND column_name = ANY(%s);
    """, (sorted(CANDIDATAS),))
    cols |= {(t, c) for t, c in cur.fetchall() if t not in EXCLUIDAS}
    # Solo tablas reales (no vistas).
    cur.execute("SELECT table_name FROM information_schema.tables "
                "WHERE table_schema='public' AND table_type='BASE TABLE';")
    reales = {t for (t,) in cur.fetchall()}
    return sorted(c for c in cols if c[0] in reales)


def verificar(cur) -> int:
    errores = 0
    cur.execute("SELECT id_interno, documento_cifrado FROM identidades;")
    boveda = cur.fetchall()
    for id_interno, cifrado in boveda:
        documento = int(descifrar(cifrado, CONTEXTO))
        if interno(documento) != id_interno:
            print(f"ERROR: la bóveda tiene un registro que no corresponde ({id_interno})")
            errores += 1
    ids = {i for i, _ in boveda}
    for tabla, columna in PK.items():
        cur.execute(f"SELECT {columna} FROM {tabla};")
        valores = [v for (v,) in cur.fetchall()]
        en_claro = [v for v in valores if not es_interno(v)]
        sin_boveda = [v for v in valores if es_interno(v) and v not in ids]
        print(f"{tabla}: {len(valores)} filas, {len(en_claro)} con documento en claro, "
              f"{len(sin_boveda)} sin registro en la bóveda")
        errores += len(en_claro) + len(sin_boveda)
    print(f"Bóveda: {len(boveda)} documentos cifrados, todos descifran y coinciden" if not errores
          else f"Verificación con {errores} errores")
    return 1 if errores else 0


def main() -> int:
    aplicar = "--aplicar" in sys.argv
    cifrar("prueba", CONTEXTO)  # falla aquí, antes de tocar nada, si falta la llave

    conn = psycopg2.connect(PG_CONNECTION_STRING)
    try:
        cur = conn.cursor()
        cur.execute(DDL)

        if "--verificar" in sys.argv:
            return verificar(cur)

        cur.execute("LOCK TABLE pacientes, usuarios IN EXCLUSIVE MODE;")
        cur.execute("SELECT numero_documento_paciente FROM pacientes "
                    "UNION SELECT numero_documento_usuario FROM usuarios;")
        documentos = sorted({d for (d,) in cur.fetchall() if not es_interno(d)})
        if not documentos:
            print("No quedan documentos en claro: la base ya estaba migrada. No se cambia nada.")
            conn.rollback()
            return 0

        mapa = {d: interno(d) for d in documentos}
        if len(set(mapa.values())) != len(mapa):
            raise SystemExit("Dos documentos dieron el mismo número interno: no se cambia nada")

        todas = llaves_foraneas(cur)
        columnas = columnas_con_documento(cur, todas)
        fks = [f for f in todas if toca(f, set(columnas))]

        # Seguridad extra: ¿hay otra columna numérica con documentos que no esté en la lista?
        cur.execute("""
            SELECT c.table_name, c.column_name FROM information_schema.columns c
            JOIN information_schema.tables t ON t.table_name = c.table_name AND t.table_schema = c.table_schema
            WHERE c.table_schema = 'public' AND t.table_type = 'BASE TABLE'
              AND c.data_type IN ('bigint', 'integer', 'numeric');
        """)
        dudosas = []
        for tabla, columna in cur.fetchall():
            if (tabla, columna) in columnas or tabla in EXCLUIDAS:
                continue
            cur.execute(f'SELECT count(*) FROM public."{tabla}" WHERE "{columna}"::numeric = ANY(%s::numeric[]);',
                        (documentos,))
            n = cur.fetchone()[0]
            if n:
                dudosas.append(f"{tabla}.{columna} ({n} valores iguales a un documento)")
        if dudosas:
            print("REVISAR: columnas fuera de la lista que tienen valores iguales a documentos:")
            for d in dudosas:
                print("  - " + d)
            if aplicar and "--forzar" not in sys.argv:
                raise SystemExit("No se aplica nada hasta revisar esas columnas (pégale esta salida a quien te ayuda)")

        cur.execute("CREATE TEMP TABLE mapa_r27(viejo BIGINT PRIMARY KEY, nuevo BIGINT NOT NULL) ON COMMIT DROP;")
        cur.executemany("INSERT INTO mapa_r27 VALUES (%s, %s);", list(mapa.items()))
        cur.executemany(
            "INSERT INTO identidades(id_interno, documento_cifrado) VALUES (%s, %s) "
            "ON CONFLICT (id_interno) DO NOTHING;",
            [(n, cifrar(str(d), CONTEXTO)) for d, n in mapa.items()])

        print(f"Documentos a cifrar: {len(mapa)}")
        print(f"Llaves foráneas que se quitan y se vuelven a crear: {len(fks)}")
        for f in fks:
            nota = "  (NO se vuelve a crear: auditoría inmutable, R28)" if f["tabla"] in EXCLUIDAS else ""
            cur.execute(f'ALTER TABLE public."{f["tabla"]}" DROP CONSTRAINT "{f["nombre"]}";')
            print(f'  - {f["tabla"]}({", ".join(f["columnas"])}) -> {f["ref"]}{nota}')

        print("Columnas actualizadas:")
        total = 0
        for tabla, columna in columnas:
            cur.execute(f'UPDATE public."{tabla}" t SET "{columna}" = m.nuevo '
                        f'FROM mapa_r27 m WHERE t."{columna}" = m.viejo;')
            cambiadas = cur.rowcount
            cur.execute(f'SELECT count(*) FROM public."{tabla}" WHERE "{columna}" IS NOT NULL '
                        f'AND ("{columna}" < %s OR "{columna}" >= %s);', (10**15, 9 * 10**15))
            otros = cur.fetchone()[0]
            aviso = f"   ({otros} valores que no son documentos conocidos: se dejan igual)" if otros else ""
            print(f"  - {tabla}.{columna}: {cambiadas} filas{aviso}")
            total += cambiadas

        for f in fks:
            if f["tabla"] not in EXCLUIDAS:
                cur.execute(f'ALTER TABLE public."{f["tabla"]}" ADD CONSTRAINT "{f["nombre"]}" {f["def"]};')
        print("Llaves foráneas recreadas y comprobadas por la base: OK")

        cur.execute("""
            INSERT INTO auditoria_cambios(tabla_afectada, registro_id, accion, datos_nuevos,
                                          realizado_por, origen)
            VALUES ('identidades', 'todas', 'EDITAR', %s, NULL, 'MIGRACION_R27');
        """, (Json({"documentos_cifrados": len(mapa), "filas_actualizadas": total,
                    "detalle": "R27: documento de identidad cifrado con AES-256-GCM"}),))

        if verificar(cur):
            raise SystemExit("La verificación falló: no se guarda nada")

        if aplicar:
            conn.commit()
            print("\nCAMBIOS GUARDADOS.")
        else:
            conn.rollback()
            print("\nSIMULACIÓN: no se guardó nada. Para aplicar: --aplicar")
        return 0
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
