import os

import psycopg2
from psycopg2 import sql
from dotenv import load_dotenv


# ============================================================
# INSPECCIÓN DE LA BD - SISTEMA DE APOYO AL TRIAGE HOSPITALARIO
# Alineado con la versión corregida de squema_bd.sql (15 tablas)
# ============================================================

load_dotenv("pass.env", override=True)

PG_CONNECTION_STRING = os.getenv("PG_CONNECTION_STRING")

if not PG_CONNECTION_STRING:
    raise ValueError("Falta PG_CONNECTION_STRING en pass.env")

conexion = psycopg2.connect(PG_CONNECTION_STRING)
cursor = conexion.cursor()


def ejecutar_y_mostrar(titulo, consulta, parametros=None):
    print(f"\n{titulo}")
    cursor.execute(consulta, parametros)
    filas = cursor.fetchall()
    if filas:
        for fila in filas:
            print(fila)
    else:
        print("Sin resultados.")


try:
    # ========================================================
    # 1. CONEXIÓN
    # ========================================================
    print("\n1. CONEXIÓN")
    cursor.execute("SELECT current_database(), current_user;")
    print(cursor.fetchone())


    # ========================================================
    # 2. TABLAS EXISTENTES
    # ========================================================
    print("\n2. TABLAS EXISTENTES")

    cursor.execute("""
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = 'public'
        ORDER BY table_name;
    """)

    tablas = [fila[0] for fila in cursor.fetchall()]

    for tabla in tablas:
        print("-", tabla)

    tablas_esperadas = {
        "roles",
        "usuarios",
        "auditoria_cambios",
        "pacientes",
        "antecedentes",
        "reportes_previos",
        "encuentros",
        "observaciones",
        "diagnosticos",
        "notas_clinicas",
        "examenes",
        "medicamentos",
        "prescripciones",
        "facturas",
        "factura_detalle",
    }

    faltantes = tablas_esperadas - set(tablas)
    extras = set(tablas) - tablas_esperadas

    print(f"\nTotal tablas encontradas: {len(tablas)}")

    if faltantes:
        print("FALTAN TABLAS:", sorted(faltantes))
    else:
        print("Las 15 tablas esperadas están presentes.")

    if extras:
        print("Tablas adicionales encontradas:", sorted(extras))


    # ========================================================
    # 3. CANTIDAD DE REGISTROS
    # ========================================================
    print("\n3. CANTIDAD DE REGISTROS")

    for tabla in sorted(tablas):
        consulta = sql.SQL("SELECT COUNT(*) FROM {};").format(
            sql.Identifier(tabla)
        )
        cursor.execute(consulta)
        cantidad = cursor.fetchone()[0]
        print(f"{tabla}: {cantidad}")


    # ========================================================
    # 4. ROLES
    # ========================================================
    print("\n4. ROLES REGISTRADOS")

    cursor.execute("""
        SELECT id_rol, nombre, descripcion, is_active
        FROM roles
        ORDER BY id_rol;
    """)

    roles = cursor.fetchall()

    if roles:
        for rol in roles:
            print(rol)
    else:
        print("La tabla roles existe, pero no contiene registros.")

    roles_esperados = {"Admin", "Medico", "Administrativo", "Paciente"}
    roles_activos = {rol[1] for rol in roles if rol[3] is True}

    if roles_activos == roles_esperados:
        print("Los 4 roles esperados están activos.")
    else:
        print("ATENCIÓN: los roles activos no coinciden con los esperados.")
        print("Esperados:", sorted(roles_esperados))
        print("Actuales:", sorted(roles_activos))


    # ========================================================
    # 5. RESTRICCIONES DE ROLES
    # ========================================================
    ejecutar_y_mostrar(
        "5. RESTRICCIONES DE LA TABLA ROLES",
        """
        SELECT
            conname,
            pg_get_constraintdef(oid)
        FROM pg_constraint
        WHERE conrelid = 'roles'::regclass
        ORDER BY conname;
        """
    )


    # ========================================================
    # 6. COLUMNAS IMPORTANTES
    # ========================================================
    print("\n6. COLUMNAS IMPORTANTES")

    tablas_revisar = (
        "usuarios",
        "pacientes",
        "encuentros",
        "observaciones",
        "diagnosticos",
        "notas_clinicas",
        "examenes",
        "medicamentos",
        "prescripciones",
        "facturas",
        "factura_detalle",
        "auditoria_cambios",
    )

    cursor.execute("""
        SELECT
            table_name,
            column_name,
            data_type,
            is_nullable,
            column_default
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name IN %s
        ORDER BY table_name, ordinal_position;
    """, (tablas_revisar,))

    tabla_anterior = None

    for tabla, columna, tipo, permite_null, valor_default in cursor.fetchall():
        if tabla != tabla_anterior:
            print(f"\n[{tabla}]")
            tabla_anterior = tabla

        print(
            f"{columna} | {tipo} | "
            f"nullable={permite_null} | default={valor_default}"
        )


    # ========================================================
    # 7. RESTRICCIONES IMPORTANTES
    # ========================================================
    print("\n7. RESTRICCIONES IMPORTANTES")

    for tabla in (
        "pacientes",
        "encuentros",
        "observaciones",
        "diagnosticos",
        "notas_clinicas",
        "examenes",
        "prescripciones",
        "facturas",
        "factura_detalle",
        "auditoria_cambios",
    ):
        print(f"\n[{tabla}]")
        cursor.execute("""
            SELECT
                conname,
                pg_get_constraintdef(oid)
            FROM pg_constraint
            WHERE conrelid = %s::regclass
            ORDER BY conname;
        """, (tabla,))

        restricciones = cursor.fetchall()

        if restricciones:
            for restriccion in restricciones:
                print(restriccion)
        else:
            print("Sin restricciones registradas.")


    # ========================================================
    # 8. ÍNDICES IMPORTANTES
    # ========================================================
    print("\n8. ÍNDICES IMPORTANTES")

    for tabla in (
        "encuentros",
        "observaciones",
        "diagnosticos",
        "notas_clinicas",
        "examenes",
        "prescripciones",
        "facturas",
        "factura_detalle",
    ):
        print(f"\n[{tabla}]")
        cursor.execute("""
            SELECT indexname, indexdef
            FROM pg_indexes
            WHERE schemaname = 'public'
              AND tablename = %s
            ORDER BY indexname;
        """, (tabla,))

        indices = cursor.fetchall()

        if indices:
            for indice in indices:
                print(indice)
        else:
            print("Sin índices.")


    # ========================================================
    # 9. VALIDACIÓN DE INTEGRIDAD REFERENCIAL
    # ========================================================
    print("\n9. VALIDACIÓN DE INTEGRIDAD REFERENCIAL")

    validaciones = {
        "Facturas con paciente distinto al del encuentro": """
            SELECT COUNT(*)
            FROM facturas f
            JOIN encuentros e
              ON e.id_encuentro = f.id_encuentro
            WHERE f.id_paciente <> e.id_paciente;
        """,

        "Detalles asociados a una factura de otro encuentro": """
            SELECT COUNT(*)
            FROM factura_detalle fd
            JOIN facturas f
              ON f.id_factura = fd.id_factura
            WHERE fd.id_encuentro <> f.id_encuentro;
        """,

        "Detalles con prescripción de otro encuentro": """
            SELECT COUNT(*)
            FROM factura_detalle fd
            JOIN prescripciones p
              ON p.id_prescripcion = fd.id_prescripcion
            WHERE fd.id_prescripcion IS NOT NULL
              AND fd.id_encuentro <> p.id_encuentro;
        """,

        "Detalles con examen de otro encuentro": """
            SELECT COUNT(*)
            FROM factura_detalle fd
            JOIN examenes ex
              ON ex.id_examen = fd.id_examen
            WHERE fd.id_examen IS NOT NULL
              AND fd.id_encuentro <> ex.id_encuentro;
        """,

        "Observaciones huérfanas": """
            SELECT COUNT(*)
            FROM observaciones o
            LEFT JOIN encuentros e
              ON e.id_encuentro = o.id_encuentro
            WHERE e.id_encuentro IS NULL;
        """,

        "Diagnósticos huérfanos": """
            SELECT COUNT(*)
            FROM diagnosticos d
            LEFT JOIN encuentros e
              ON e.id_encuentro = d.id_encuentro
            WHERE e.id_encuentro IS NULL;
        """,

        "Notas clínicas huérfanas": """
            SELECT COUNT(*)
            FROM notas_clinicas n
            LEFT JOIN encuentros e
              ON e.id_encuentro = n.id_encuentro
            WHERE e.id_encuentro IS NULL;
        """,

        "Exámenes huérfanos": """
            SELECT COUNT(*)
            FROM examenes ex
            LEFT JOIN encuentros e
              ON e.id_encuentro = ex.id_encuentro
            WHERE e.id_encuentro IS NULL;
        """,

        "Prescripciones huérfanas": """
            SELECT COUNT(*)
            FROM prescripciones p
            LEFT JOIN encuentros e
              ON e.id_encuentro = p.id_encuentro
            WHERE e.id_encuentro IS NULL;
        """,

        "Prescripciones con medicamento inexistente": """
            SELECT COUNT(*)
            FROM prescripciones p
            LEFT JOIN medicamentos m
              ON m.codigo_cum = p.codigo_cum
            WHERE m.codigo_cum IS NULL;
        """,

        "Pacientes con más de un encuentro activo": """
            SELECT COUNT(*)
            FROM (
                SELECT id_paciente
                FROM encuentros
                WHERE is_deleted = false
                  AND estado <> 'finalizado'
                GROUP BY id_paciente
                HAVING COUNT(*) > 1
            ) x;
        """,

        "Encuentros sin paciente válido": """
            SELECT COUNT(*)
            FROM encuentros e
            LEFT JOIN pacientes p
              ON p.numero_documento_paciente = e.id_paciente
            WHERE p.numero_documento_paciente IS NULL;
        """,
    }

    errores_integridad = 0

    for nombre, consulta in validaciones.items():
        cursor.execute(consulta)
        cantidad = cursor.fetchone()[0]
        print(f"{nombre}: {cantidad}")
        errores_integridad += cantidad


    # ========================================================
    # 10. VALIDACIÓN DE CAMPOS NORMALIZADOS
    # ========================================================
    print("\n10. VALIDACIÓN DE CAMPOS NORMALIZADOS")

    cursor.execute("""
        SELECT COUNT(*)
        FROM pacientes
        WHERE genero_fhir IS NOT NULL
          AND genero_fhir NOT IN ('male','female','other','unknown');
    """)
    generos_invalidos = cursor.fetchone()[0]
    print(f"Pacientes con genero_fhir inválido: {generos_invalidos}")

    cursor.execute("""
        SELECT COUNT(*)
        FROM encuentros
        WHERE nivel_triage IS NOT NULL
          AND nivel_triage NOT BETWEEN 1 AND 5;
    """)
    triage_invalidos = cursor.fetchone()[0]
    print(f"Encuentros con nivel_triage inválido: {triage_invalidos}")

    cursor.execute("""
        SELECT COUNT(*)
        FROM encuentros
        WHERE dolor_escala IS NOT NULL
          AND dolor_escala NOT BETWEEN 0 AND 10;
    """)
    dolor_invalido = cursor.fetchone()[0]
    print(f"Encuentros con dolor_escala inválido: {dolor_invalido}")


    # ========================================================
    # 11. TRAZABILIDAD DE AUTORÍA
    # ========================================================
    print("\n11. TRAZABILIDAD DE AUTORÍA")

    consultas_autoria = {
        "Antecedentes sin autor válido": """
            SELECT COUNT(*)
            FROM antecedentes a
            LEFT JOIN usuarios u
              ON u.numero_documento_usuario = a.registrado_por
            WHERE u.numero_documento_usuario IS NULL;
        """,

        "Observaciones sin autor válido": """
            SELECT COUNT(*)
            FROM observaciones o
            LEFT JOIN usuarios u
              ON u.numero_documento_usuario = o.registrado_por
            WHERE u.numero_documento_usuario IS NULL;
        """,

        "Diagnósticos sin autor válido": """
            SELECT COUNT(*)
            FROM diagnosticos d
            LEFT JOIN usuarios u
              ON u.numero_documento_usuario = d.registrado_por
            WHERE u.numero_documento_usuario IS NULL;
        """,

        "Notas clínicas sin autor válido": """
            SELECT COUNT(*)
            FROM notas_clinicas n
            LEFT JOIN usuarios u
              ON u.numero_documento_usuario = n.registrado_por
            WHERE u.numero_documento_usuario IS NULL;
        """,

        "Exámenes sin solicitante válido": """
            SELECT COUNT(*)
            FROM examenes ex
            LEFT JOIN usuarios u
              ON u.numero_documento_usuario = ex.solicitado_por
            WHERE u.numero_documento_usuario IS NULL;
        """,

        "Prescripciones sin autor válido": """
            SELECT COUNT(*)
            FROM prescripciones p
            LEFT JOIN usuarios u
              ON u.numero_documento_usuario = p.prescrito_por
            WHERE u.numero_documento_usuario IS NULL;
        """,
    }

    errores_autoria = 0

    for nombre, consulta in consultas_autoria.items():
        cursor.execute(consulta)
        cantidad = cursor.fetchone()[0]
        print(f"{nombre}: {cantidad}")
        errores_autoria += cantidad


    # ========================================================
    # 12. RESUMEN FINAL
    # ========================================================
    print("\n12. RESUMEN FINAL")

    total_errores = (
        len(faltantes)
        + errores_integridad
        + generos_invalidos
        + triage_invalidos
        + dolor_invalido
        + errores_autoria
    )

    if total_errores == 0:
        print("BD COHERENTE: estructura, relaciones y datos pasaron las validaciones principales.")
    else:
        print(f"ATENCIÓN: se detectaron {total_errores} problemas en las validaciones.")

finally:
    cursor.close()
    conexion.close()

print("\nInspección finalizada. No se modificó ningún dato.")
