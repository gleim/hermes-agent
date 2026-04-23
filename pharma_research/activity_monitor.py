#!/usr/bin/env python3
"""
Activity Monitoring & Visualization System for Pharma Research Loop
Generates visual and text records of all loop activities
"""

import json
import os
import datetime
import subprocess
from pathlib import Path

OUTPUT_DIR = Path.home() / "pharma_research"
OUTPUT_DIR.mkdir(exist_ok=True)

def log_activity(activity_type, details, status="success"):
    """Log an activity with timestamp and status"""
    activity = {
        "timestamp": datetime.datetime.now().isoformat(),
        "activity_type": activity_type,
        "status": status,
        "details": details
    }
    
    # Append to master log
    log_file = OUTPUT_DIR / "activity_master.json"
    logs = []
    if log_file.exists():
        with open(log_file) as f:
            logs = json.load(f)
    logs.append(activity)
    with open(log_file, 'w') as f:
        json.dump(logs, f, indent=2)
    
    return activity, logs

def create_text_record(logs):
    """Create comprehensive text record"""
    successful = [l for l in logs if l["status"] == "success"]
    failed = [l for l in logs if l["status"] == "failed"]
    pending = [l for l in logs if l["status"] == "pending"]
    
    record = {
        "record_type": "activity_log",
        "generated_at": datetime.datetime.now().isoformat(),
        "total_activities": len(logs),
        "summary": {
            "successful": len(successful),
            "failed": len(failed),
            "pending": len(pending)
        },
        "activities": logs
    }
    return record

def create_visualization(logs):
    """Create ASCII visualization"""
    # Count by type
    counts = {}
    for l in logs:
        t = l["activity_type"]
        counts[t] = counts.get(t, 0) + 1
    
    if not counts:
        return "No activities recorded yet"
    
    max_count = max(counts.values())
    viz = "LOOP ACTIVITY VISUALIZATION\n"
    viz += "=" * 50 + "\n\n"
    
    for activity_type, count in counts.items():
        bar_len = int((count / max_count) * 30)
        bar = "█" * bar_len
        viz += f"{activity_type:20s} |{bar} {count}\n"
    
    viz += "\n" + "=" * 50 + "\n\n"
    viz += "TIMELINE:\n"
    viz += "-" * 50 + "\n"
    
    for i, activity in enumerate(logs[-10:], 1):
        icon = "✓" if activity["status"] == "success" else "✗"
        viz += f"{i:2d}. [{icon}] {activity['timestamp'][-19:]} - {activity['activity_type']}\n"
    
    return viz

def generate_report():
    """Generate complete activity report"""
    log_file = OUTPUT_DIR / "activity_master.json"
    logs = json.loads(log_file.read_text()) if log_file.exists() else []
    
    # Create text record
    text_record = create_text_record(logs)
    text_file = OUTPUT_DIR / f"activity_log_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    text_file.write_text(json.dumps(text_record, indent=2))
    
    # Create visualization
    viz = create_visualization(logs)
    viz_file = OUTPUT_DIR / f"activity_visualization_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    viz_file.write_text(viz)
    
    # Create combined record
    combined = {
        "text_record": text_record,
        "visualization": viz,
        "metadata": {
            "total_activities": len(logs),
            "generated_at": datetime.datetime.now().isoformat()
        }
    }
    comb_file = OUTPUT_DIR / f"loop_activities_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    comb_file.write_text(json.dumps(combined, indent=2))
    
    return viz, text_file, comb_file

if __name__ == "__main__":
    # Example usage
    log_activity("ccxt_fetch", "Retrieved 18 markets")
    log_activity("drug_analysis", "Analyzed Imatinib properties")
    
    viz, text, combined = generate_report()
    print(f"Visualization: {viz}")
    print(f"Text record: {text}")
    print(f"Combined: {combined}")
