from fastapi import APIRouter,Depends
from psycopg2.extras import RealDictCursor

from auth.service import requerir_roles
from core.database import get_db

router=APIRouter()

@router.get("/roles",tags=["Catálogos"])
def listar_roles(db=Depends(get_db),u=Depends(requerir_roles("Admin"))):
    cur=db.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute("""
            SELECT id_rol,nombre,descripcion,is_active
            FROM roles
            WHERE is_active=TRUE
            ORDER BY id_rol;
        """)
        return cur.fetchall()
    finally:
        cur.close()

@router.get("/especialidades",tags=["Catálogos"])
def listar_especialidades(db=Depends(get_db),u=Depends(requerir_roles("Admin","Medico","Especialista"))):
    cur=db.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute("""
            SELECT id_especialidad,nombre,descripcion,activo
            FROM especialidades
            WHERE activo=TRUE
            ORDER BY nombre;
        """)
        return cur.fetchall()
    finally:
        cur.close()

@router.get("/especialistas",tags=["Catálogos"])
def listar_especialistas(
    id_especialidad:int|None=None,
    db=Depends(get_db),
    u=Depends(requerir_roles("Admin","Medico"))
):
    cur=db.cursor(cursor_factory=RealDictCursor)
    try:
        params=[]
        filtro=""
        if id_especialidad is not None:
            filtro=" AND ue.id_especialidad=%s"
            params.append(id_especialidad)
        cur.execute(f"""
            SELECT DISTINCT
                us.numero_documento_usuario,
                us.username,
                us.nombres,
                us.apellidos,
                e.id_especialidad,
                e.nombre AS especialidad
            FROM usuarios us
            JOIN roles r ON r.id_rol=us.id_rol
            JOIN usuario_especialidades ue
              ON ue.numero_documento_usuario=us.numero_documento_usuario
            JOIN especialidades e ON e.id_especialidad=ue.id_especialidad
            WHERE r.nombre='Especialista'
              AND us.estado=TRUE
              AND us.is_deleted=FALSE
              AND e.activo=TRUE
              {filtro}
            ORDER BY us.apellidos,us.nombres,e.nombre;
        """,params)
        return cur.fetchall()
    finally:
        cur.close()
