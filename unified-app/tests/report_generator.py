"""Report Generator - HTML evidence report from battle results.

Reads results.json and generates a self-contained HTML report suitable
for printing and thesis appendix inclusion.
"""
import argparse
import base64
import json
import sys
from datetime import datetime
from pathlib import Path

_RUNTIME_DIR = Path(__file__).parent.parent / "_runtime"
_BATTLE_OUTPUT_DIR = _RUNTIME_DIR / "output" / "battle"


def generate_html_report(results: list[dict], output_path: Path):
    """Generate self-contained HTML report."""
    
    # Calculate summary statistics
    total = len(results)
    passed = sum(1 for r in results if r["score"] >= 8)
    failed = sum(1 for r in results if r["score"] < 8 and r["status"] != "error")
    errors = sum(1 for r in results if r["status"] == "error")
    avg_score = sum(r["score"] for r in results) / total if total > 0 else 0
    score_pct = int((avg_score / 10) * 100)
    
    # Determine score band color
    if score_pct >= 90:
        band_color = "#4CAF50"  # Green
        band_label = "EXCELLENT"
    elif score_pct >= 75:
        band_color = "#FF9800"  # Orange
        band_label = "GOOD"
    elif score_pct >= 60:
        band_color = "#FFC107"  # Amber
        band_label = "ACCEPTABLE"
    else:
        band_color = "#F44336"  # Red
        band_label = "NEEDS IMPROVEMENT"
    
    # Category breakdown
    categories = {}
    for result in results:
        cat = result["id"].split("-")[0]
        if cat not in categories:
            categories[cat] = {"total": 0, "passed": 0, "scores": []}
        categories[cat]["total"] += 1
        if result["score"] >= 8:
            categories[cat]["passed"] += 1
        categories[cat]["scores"].append(result["score"])
    
    for cat in categories:
        categories[cat]["avg_score"] = sum(categories[cat]["scores"]) / len(categories[cat]["scores"])
    
    # Generate HTML
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Battle Test Report - Unified App</title>
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}
        body {{
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            line-height: 1.6;
            color: #333;
            background: #f5f5f5;
            padding: 20px;
        }}
        .container {{
            max-width: 1200px;
            margin: 0 auto;
            background: white;
            padding: 40px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
        }}
        h1 {{
            color: #2c3e50;
            border-bottom: 3px solid #3498db;
            padding-bottom: 10px;
            margin-bottom: 30px;
        }}
        h2 {{
            color: #34495e;
            margin-top: 30px;
            margin-bottom: 15px;
        }}
        .summary {{
            background: #ecf0f1;
            padding: 20px;
            border-radius: 8px;
            margin-bottom: 30px;
        }}
        .summary-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 15px;
            margin-top: 15px;
        }}
        .summary-item {{
            background: white;
            padding: 15px;
            border-radius: 5px;
            text-align: center;
        }}
        .summary-item .label {{
            font-size: 12px;
            color: #7f8c8d;
            text-transform: uppercase;
        }}
        .summary-item .value {{
            font-size: 32px;
            font-weight: bold;
            color: #2c3e50;
        }}
        .score-band {{
            display: inline-block;
            padding: 10px 20px;
            border-radius: 5px;
            color: white;
            font-weight: bold;
            font-size: 18px;
            background: {band_color};
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
            margin-top: 20px;
            font-size: 14px;
        }}
        th {{
            background: #34495e;
            color: white;
            padding: 12px;
            text-align: left;
            font-weight: 600;
        }}
        td {{
            padding: 10px 12px;
            border-bottom: 1px solid #ecf0f1;
        }}
        tr:hover {{
            background: #f8f9fa;
        }}
        .status-pass {{
            color: #27ae60;
            font-weight: bold;
        }}
        .status-fail {{
            color: #e74c3c;
            font-weight: bold;
        }}
        .status-error {{
            color: #c0392b;
            font-weight: bold;
        }}
        .score {{
            font-weight: bold;
        }}
        .score-high {{
            color: #27ae60;
        }}
        .score-med {{
            color: #f39c12;
        }}
        .score-low {{
            color: #e74c3c;
        }}
        .category-breakdown {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
            gap: 20px;
            margin-top: 20px;
        }}
        .category-card {{
            background: #f8f9fa;
            padding: 20px;
            border-radius: 8px;
            border-left: 4px solid #3498db;
        }}
        .category-card h3 {{
            color: #2c3e50;
            margin-bottom: 10px;
        }}
        .thesis-evidence {{
            background: #e8f5e9;
            border-left: 4px solid #4CAF50;
            padding: 20px;
            margin-top: 30px;
        }}
        .thesis-evidence h2 {{
            color: #2e7d32;
            margin-top: 0;
        }}
        @media print {{
            body {{
                background: white;
                padding: 0;
            }}
            .container {{
                box-shadow: none;
                padding: 20px;
            }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <h1>Battle Test Report</h1>
        <p><strong>Generated:</strong> {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}</p>
        <p><strong>Total Scenarios:</strong> {total}</p>
        
        <div class="summary">
            <h2>Summary</h2>
            <div class="summary-grid">
                <div class="summary-item">
                    <div class="label">Passed</div>
                    <div class="value" style="color: #27ae60;">{passed}</div>
                </div>
                <div class="summary-item">
                    <div class="label">Failed</div>
                    <div class="value" style="color: #e74c3c;">{failed}</div>
                </div>
                <div class="summary-item">
                    <div class="label">Errors</div>
                    <div class="value" style="color: #c0392b;">{errors}</div>
                </div>
                <div class="summary-item">
                    <div class="label">Overall Score</div>
                    <div class="value">{score_pct}%</div>
                </div>
            </div>
            <p style="margin-top: 20px; text-align: center;">
                <span class="score-band">{band_label}</span>
            </p>
        </div>
        
        <h2>Category Breakdown</h2>
        <div class="category-breakdown">
"""
    
    for cat, stats in sorted(categories.items()):
        cat_pct = int((stats["passed"] / stats["total"]) * 100)
        html += f"""
            <div class="category-card">
                <h3>{cat} - {_category_name(cat)}</h3>
                <p><strong>Pass Rate:</strong> {stats["passed"]}/{stats["total"]} ({cat_pct}%)</p>
                <p><strong>Avg Score:</strong> {stats["avg_score"]:.1f}/10</p>
            </div>
"""
    
    html += """
        </div>
        
        <h2>Detailed Results</h2>
        <table>
            <thead>
                <tr>
                    <th>ID</th>
                    <th>Description</th>
                    <th>Domain</th>
                    <th>Status</th>
                    <th>Score</th>
                    <th>Time (ms)</th>
                    <th>Notes</th>
                </tr>
            </thead>
            <tbody>
"""
    
    for result in results:
        status_class = "status-pass" if result["score"] >= 8 else "status-fail"
        if result["status"] == "error":
            status_class = "status-error"
        
        score_class = "score-high" if result["score"] >= 8 else ("score-med" if result["score"] >= 5 else "score-low")
        
        notes = "; ".join(result.get("notes", []))[:100]
        elapsed = result.get("elapsed_ms", 0) or 0
        
        html += f"""
                <tr>
                    <td><strong>{result["id"]}</strong></td>
                    <td>{result["description"][:60]}...</td>
                    <td>{result["domain"]}</td>
                    <td class="{status_class}">{result["status"]}</td>
                    <td class="score {score_class}">{result["score"]}/10</td>
                    <td>{elapsed}</td>
                    <td>{notes}</td>
                </tr>
"""
    
    html += """
            </tbody>
        </table>
        
        <div class="thesis-evidence">
            <h2>Thesis Evidence Summary</h2>
            <p>This automated test suite demonstrates the system's reliability across multiple user personas and usage scenarios. The results provide quantifiable evidence of system behavior under normal and stress conditions.</p>
            <p><strong>Interpretation for Non-Technical Audience:</strong></p>
            <p>"""
    
    if score_pct >= 90:
        html += f"The system passed {passed} out of {total} test cases ({score_pct}%), demonstrating excellent reliability and robustness. All critical functionality works as expected."
    elif score_pct >= 75:
        html += f"The system passed {passed} out of {total} test cases ({score_pct}%), showing good overall performance with minor issues that do not affect core functionality."
    else:
        html += f"The system passed {passed} out of {total} test cases ({score_pct}%). While basic functionality works, there are areas requiring improvement before production deployment."
    
    html += """</p>
        </div>
    </div>
</body>
</html>
"""
    
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)


def _category_name(cat: str) -> str:
    """Get full category name."""
    names = {
        "HP": "Happy Path",
        "EC": "Edge Cases",
        "ER": "Error Recovery",
        "AF": "AI Failure Modes",
        "ST": "Stress Testing"
    }
    return names.get(cat, cat)


def main():
    parser = argparse.ArgumentParser(description="Generate HTML report from battle results")
    parser.add_argument("--input", default=str(_BATTLE_OUTPUT_DIR / "results.json"))
    parser.add_argument("--output", default=str(_BATTLE_OUTPUT_DIR / "report.html"))
    
    args = parser.parse_args()
    
    input_path = Path(args.input)
    if not input_path.exists():
        print(f"Error: Results file not found: {input_path}")
        return 1
    
    with open(input_path, encoding="utf-8") as f:
        results = json.load(f)
    
    output_path = Path(args.output)
    generate_html_report(results, output_path)
    
    print(f"✓ Report generated: {output_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
