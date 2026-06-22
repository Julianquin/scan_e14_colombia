#!/usr/bin/env python3
"""
Etiquetador visual de dígitos E-14 (solo stdlib: tkinter + csv).

Muestra cada cajita grande con su sugerencia y registras el dígito de un tecleo.
Edita el CSV in situ: solo recorre las filas con 'etiqueta_digito' vacío, así
que tras 'pseudoetiquetar' solo te muestra el residuo dudoso.

Uso:
    python etiquetador.py dataset_digitos/etiquetas.csv dataset_digitos/cajas

Teclas:  0-9 etiqueta y avanza · Enter acepta la sugerencia · ← atrás ·
         Espacio salta · Esc guarda y sale.  (guarda cada 25)
"""
import csv, argparse, tkinter as tk
from pathlib import Path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("etiquetas_csv")
    ap.add_argument("cajas_dir")
    ap.add_argument("--zoom", type=int, default=9)
    a = ap.parse_args()

    rows = list(csv.DictReader(open(a.etiquetas_csv, encoding="utf-8-sig")))
    campos = list(rows[0].keys())
    if "fuente" not in campos:
        campos.append("fuente")
        for r in rows:
            r.setdefault("fuente", "")
    pend = [i for i, r in enumerate(rows) if not r["etiqueta_digito"].strip()]
    if not pend:
        print("No hay cajitas pendientes de etiquetar."); return
    print(f"Pendientes: {len(pend)}")

    st = {"k": 0}
    root = tk.Tk(); root.title("Etiquetador E-14")
    img_lbl = tk.Label(root); img_lbl.pack(padx=20, pady=20)
    info = tk.Label(root, font=("Consolas", 16)); info.pack()
    prog = tk.Label(root, font=("Consolas", 11), fg="#666"); prog.pack(pady=6)

    def guardar():
        with open(a.etiquetas_csv, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=campos); w.writeheader(); w.writerows(rows)

    def mostrar():
        if st["k"] >= len(pend):
            guardar(); info.config(text="¡Terminado! (guardado)"); prog.config(text=""); img_lbl.config(image=""); return
        r = rows[pend[st["k"]]]
        ph = tk.PhotoImage(file=str(Path(a.cajas_dir) / r["caja"])).zoom(a.zoom)
        img_lbl.config(image=ph); img_lbl.image = ph
        sug = r.get("sugerencia", "") or "—"
        info.config(text=f'{r["etiqueta_celda"]}  pos{r["pos"]}     sugerencia: {sug}')
        prog.config(text=f'{st["k"]+1} / {len(pend)}     '
                         f'0-9 etiqueta · Enter=sugerencia · ←atrás · Espacio salta · Esc sale')

    def set_d(d):
        r = rows[pend[st["k"]]]
        r["etiqueta_digito"] = d; r["fuente"] = "manual"
        st["k"] += 1
        if st["k"] % 25 == 0:
            guardar()
        mostrar()

    for d in "0123456789":
        root.bind(d, lambda e, d=d: set_d(d))
    root.bind("<Return>", lambda e: (lambda s: set_d(s) if s in "0123456789" else None)(rows[pend[st["k"]]].get("sugerencia", "").strip()))
    root.bind("<space>", lambda e: (st.update(k=st["k"] + 1), mostrar()))
    root.bind("<Left>", lambda e: (st.update(k=max(0, st["k"] - 1)), mostrar()))
    root.bind("<Escape>", lambda e: (guardar(), root.destroy()))
    mostrar(); root.mainloop()


if __name__ == "__main__":
    main()
