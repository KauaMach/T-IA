import csv
import os
from collections import Counter, defaultdict
from datetime import datetime

# Caminhos baseados na raiz do projeto
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
PATH_CSV = os.path.join(BASE_DIR, "data/raw/diario_oficial/webscraping_diario.csv")    
PATH_RELATORIO = os.path.join(BASE_DIR, "data/processed/relatorio_diario.md")

# Mapeamento de Regiões e seus Municípios
REGIOES = {
    "Tabuleiros do Alto Parnaíba": [
        "Antônio Almeida", "Baixa Grande do Ribeiro", "Bertolínia", "Canavieira", 
        "Guadalupe", "Jerumenha", "Landri Sales", "Marcos Parente", 
        "Porto Alegre do Piauí", "Ribeiro Gonçalves", "Sebastião Leal", "Uruçuí"
    ],
    "Vale dos Rios Piauí e Itaueiras": [
        "Arraial", "Brejo do Pi", "Canto do Buriti", "Floriano", 
        "Flores do Pi", "Francisco Ayres", "Itaueira", "Nazare do Pi", 
        "Nova Santa Rita", "Pajeu do Pi", "Pavussu", "Paes Landim", 
        "Pedro Laurentino", "Ribeira do Pi", "Rio Grande do Pi", 
        "Sao Jose do Peixe", "Sao Miguel do Fidalgo", "Socorro do Pi", 
        "Tamboril do Pi"
    ]
}

# Inverte o mapeamento para busca rápida
MUNICIPIO_PARA_REGIAO = {m: r for r, municipios in REGIOES.items() for m in municipios}

def gerar():
    if not os.path.exists(PATH_CSV):
        print(f"[!] Arquivo {PATH_CSV} não encontrado.")
        return

    with open(PATH_CSV, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f, delimiter="|")
        dados = list(reader)

    total_registros = len(dados)
    if total_registros == 0:
        print("[!] Nenhum dado encontrado no CSV para gerar o relatório.")
        return
    
    # Contadores e Agrupamentos
    regioes_stats = Counter()
    municipios = Counter()
    categorias = Counter()
    distribuicao_mensal = Counter()
    matriz_mun_ent = defaultdict(lambda: Counter())
    
    datas = []
    
    for d in dados:
        m = d['Município']
        e = d['Entidade']
        c = d['Categoria']
        data_str = d['Data']
        
        regiao = MUNICIPIO_PARA_REGIAO.get(m, "Outros")
        regioes_stats[regiao] += 1
        
        municipios[m] += 1
        categorias[c] += 1
        matriz_mun_ent[m][e] += 1
        
        try:
            dt = datetime.strptime(data_str, "%d/%m/%Y")
            datas.append(dt)
            mes_chave = dt.strftime("%Y-%m")
            mes_nome = dt.strftime("%B")
            distribuicao_mensal[f"{mes_chave} ({mes_nome})"] += 1
        except:
            pass

    # Metadados de Tempo
    periodo_inicio = min(datas).strftime("%d/%m/%Y") if datas else "N/A"
    periodo_fim = max(datas).strftime("%d/%m/%Y") if datas else "N/A"

    relatorio = [
        "# 📊 Relatório Detalhado de Coleta — 2025",
        f"\n> **Total de Registros:** {total_registros}",
        f"> **Período Coberto:** {periodo_inicio} até {periodo_fim}",
        "\n## 🌍 Resumo por Região",
        "| Região | Registros | % |",
        "| :--- | :---: | :---: |"
    ]

    for reg, count in sorted(regioes_stats.items()):
        pct = (count / total_registros) * 100
        relatorio.append(f"| {reg} | {count} | {pct:.1f}% |")

    relatorio.append("\n## 📍 Matriz Município vs Entidade")
    relatorio.append("Detalhamento por região e órgão.")

    for regiao, lista_municipios in REGIOES.items():
        relatorio.append(f"\n### {regiao}")
        relatorio.append("| Município | Prefeitura | Câmara | **Total** |")
        relatorio.append("| :--- | :---: | :---: | :---: |")
        
        # Filtra apenas municípios desta região que possuem dados
        municipios_regiao = [m for m in lista_municipios if m in municipios]
        for m in sorted(municipios_regiao):
            pref = matriz_mun_ent[m]['Prefeitura']
            cam = matriz_mun_ent[m]['Camara']
            total = pref + cam
            relatorio.append(f"| {m} | {pref} | {cam} | **{total}** |")
        
        if not municipios_regiao:
            relatorio.append("| - | - | - | - |")

    relatorio.extend([
        "\n## 📅 Evolução Mensal",
        "Quantidade de publicações detectadas por mês.",
        "\n| Mês | Publicações | % |",
        "| :--- | :---: | :---: |"
    ])
    
    for mes in sorted(distribuicao_mensal.keys()):
        count = distribuicao_mensal[mes]
        pct = (count / total_registros) * 100
        relatorio.append(f"| {mes} | {count} | {pct:.1f}% |")

    relatorio.extend([
        "\n## 📂 Classificação por Categoria (Top 15)",
        "\n| Categoria | Total | % |",
        "| :--- | :---: | :---: |"
    ])
    for c, count in categorias.most_common(15):
        pct = (count / total_registros) * 100
        relatorio.append(f"| {c} | {count} | {pct:.1f}% |")

    relatorio.append(f"\n\n---\n*Relatório gerado automaticamente em {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}*")

    with open(PATH_RELATORIO, 'w', encoding='utf-8') as f:
        f.write("\n".join(relatorio))

    print(f"[*] Relatório detalhado gerado: {PATH_RELATORIO}")

if __name__ == "__main__":
    gerar()
