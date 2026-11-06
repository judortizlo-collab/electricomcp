"""Ejecuta el backend de AutoCAD contra un AutoCAD simulado (sin Windows).

No reemplaza la prueba real en AutoCAD 2026, pero detecta errores de lógica,
llamadas inexistentes en el flujo y fallas de los reintentos COM.
"""

import importlib
import sys
import types


class Obj:
    def __init__(self, nombre="obj", log=None):
        self.__dict__["_n"] = nombre
        self.__dict__["_log"] = log if log is not None else []
        self.__dict__["_items"] = {}

    def __getattr__(self, k):
        def metodo(*a, **kw):
            self._log.append(k)
            if k == "Item":
                if a[0] in self._items:
                    return self._items[a[0]]
                raise KeyError(a[0])
            o = Obj(k, self._log)
            if k == "Add" and self._n in ("Blocks", "Layers", "TextStyles"):
                self._items[a[-1] if self._n == "Blocks" else a[0]] = o
            if k == "GetAttributes":
                att = Obj("att", self._log)
                att.__dict__["TagString"] = "CIRCUITO"
                return [att]
            return o
        return metodo

    def __setattr__(self, k, v):
        self._log.append(f"set:{k}")
        self.__dict__[k] = v

    def __iter__(self):
        return iter([])


def test_backend_autocad_simulado(monkeypatch):
    log = []
    doc = Obj("doc", log)
    for col in ("Blocks", "Layers", "TextStyles", "Linetypes"):
        doc.__dict__[col] = Obj(col, log)
    doc.__dict__["ModelSpace"] = Obj("ms", log)
    acad = Obj("acad", log)
    acad.__dict__["Documents"] = Obj("Documents", log)
    acad.__dict__["Documents"].__dict__["Count"] = 1
    acad.__dict__["ActiveDocument"] = doc
    acad.__dict__["Documents"].__dict__["Add"] = lambda *a: doc

    win32 = types.ModuleType("win32com.client")
    win32.GetActiveObject = lambda name: acad
    win32.Dispatch = lambda name: acad
    win32.VARIANT = lambda t, v: ("VARIANT", t, v)
    pythoncom = types.ModuleType("pythoncom")
    pythoncom.CoInitialize = lambda: None
    pythoncom.VT_ARRAY, pythoncom.VT_R8, pythoncom.VT_DISPATCH = 8192, 5, 9
    pkg = types.ModuleType("win32com")
    pkg.client = win32
    monkeypatch.setitem(sys.modules, "win32com", pkg)
    monkeypatch.setitem(sys.modules, "win32com.client", win32)
    monkeypatch.setitem(sys.modules, "pythoncom", pythoncom)

    import electromcp.backends.autocad_com as mod
    mod = importlib.reload(mod)

    sys.path.insert(0, "examples")
    from demo_apartamento import construir
    from electromcp.render import Renderizador

    res = Renderizador(construir(), mod.AutoCADBackend(nuevo_dibujo=True)).dibujar_juego()
    assert res.startswith("Dibujado en AutoCAD")
    assert log.count("InsertBlock") > 50
    assert "AddHatch" in log and "AddLightWeightPolyline" in log and "AddAttribute" in log
