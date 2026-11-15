"""R28: demuestra que la auditoría encadenada detecta manipulaciones.

Desde la carpeta back/:   python scripts/prueba_r28_manipulacion.py

Es SEGURO sobre la base real: cada manipulación se hace dentro de una transacción
que se REVIERTE al final, de modo que ningún registro queda alterado. Lo que
imprime sirve como evidencia (captura) para R34 y STRIDE.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import psycopg2

from core.config import PG_CONNECTION_STRING

fallos = 0


def verificar(cur):
    cur.execute("SELECT ok, total, sin_encadenar, primer_roto, id_roto, motivo, hash_cabeza "
                "FROM auditoria_verificar_cadena();")
    ok, total, sin, seq, id_roto, motivo, cabeza = cur.fetchone()
    return {"ok": ok, "total": total, "sin_encadenar": sin, "primer_roto": seq,
            "id_roto": id_roto, "motivo": motivo, "cabeza": cabeza}


def comprobar(descripcion, condicion, detalle=""):
    global fallos
    print(("OK     " if condicion else "FALLA  ") + descripcion + (f"   [{detalle}]" if not condicion else ""))
    fallos += (not condicion)


def main():
    conn = psycopg2.connect(PG_CONNECTION_STRING)
    conn.autocommit = False
    cur = conn.cursor()
    try:
        inicial = verificar(cur)
        conn.rollback()
        print(f"Estado inicial: {inicial['total']} eslabones, íntegra={inicial['ok']}, "
              f"cabeza={str(inicial['cabeza'])[:16]}...\n")
        if not inicial["ok"]:
            sys.exit("La cadena real YA está rota: investigue eso antes de hacer esta demostración.")
        if inicial["total"] < 3:
            sys.exit("Hay muy pocos registros de auditoría para la demostración (se necesitan al menos 3).")

        cur.execute("SELECT cadena_seq, id_auditoria FROM auditoria_cambios "
                    "WHERE cadena_seq IS NOT NULL ORDER BY cadena_seq OFFSET %s LIMIT 1;",
                    (inicial["total"] // 2,))
        seq, id_aud = cur.fetchone()
        conn.rollback()
        print(f"Registro elegido para la prueba: id_auditoria={id_aud} (eslabón {seq})\n")

        # 1. Alterar el contenido de un registro.
        cur.execute("UPDATE auditoria_cambios SET datos_nuevos = '{\"alterado\": true}'::jsonb "
                    "WHERE cadena_seq = %s;", (seq,))
        v = verificar(cur)
        comprobar("1. Editar un registro -> la verificación falla", v["ok"] is False, v)
        comprobar("   y señala el registro exacto con motivo CONTENIDO_ALTERADO",
                  v["primer_roto"] == seq and v["motivo"] == "CONTENIDO_ALTERADO", v)
        conn.rollback()

        # 2. Borrar un registro intermedio.
        cur.execute("DELETE FROM auditoria_cambios WHERE cadena_seq = %s;", (seq,))
        v = verificar(cur)
        comprobar("2. Borrar un registro -> la verificación falla", v["ok"] is False, v)
        comprobar("   y lo detecta como SECUENCIA_CON_HUECO en el eslabón siguiente",
                  v["primer_roto"] == seq + 1 and v["motivo"] == "SECUENCIA_CON_HUECO", v)
        conn.rollback()

        # 3. Cambiar la acción registrada.
        cur.execute("UPDATE auditoria_cambios SET accion = 'ELIMINAR' WHERE cadena_seq = %s;", (seq,))
        v = verificar(cur)
        comprobar("3. Cambiar la acción registrada -> la verificación falla", v["ok"] is False, v)
        conn.rollback()

        # 4. Todo se revirtió.
        final = verificar(cur)
        conn.rollback()
        comprobar("4. Tras revertir las manipulaciones la cadena real sigue íntegra",
                  final["ok"] and final["total"] == inicial["total"] and final["cabeza"] == inicial["cabeza"], final)
    finally:
        conn.rollback()
        conn.close()
    print("\nRESULTADO:", "TODO OK" if fallos == 0 else f"{fallos} comprobación(es) fallaron")
    sys.exit(1 if fallos else 0)


if __name__ == "__main__":
    main()
    