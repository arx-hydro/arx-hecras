# -*- coding: utf-8 -*-
"""
Spyder Editor

This is a temporary script file.
"""

import win32com.client
import time
import multiprocessing
import os
import pythoncom
import traceback

def run_hecras(project_path, plan_name, log_path):
    try:
        pythoncom.CoInitialize()

        with open(log_path, "w") as log:
            def log_print(msg):
                print(msg)
                log.write(msg + "\n")
                log.flush()

            log_print(f"Starting HEC-RAS for: {project_path}, Plan: {plan_name}")
            ras = win32com.client.Dispatch("RAS66.HECRASController")
            ras.ShowRas()
            time.sleep(2)

            ras.Project_Open(project_path)
            time.sleep(2)
            ras.Plan_SetCurrent(plan_name)
            ras.Compute_CurrentPlan()

            while ras.Processing_Status != 0:
                log_print(f"[{plan_name}] Simulation running...")
                time.sleep(5)

            log_print(f"[{plan_name}] Simulation complete.")
            ras.Project_Close()
            log_print(f"[{plan_name}] Project closed.")

    except Exception:
        with open(log_path, "a") as log:
            log.write("Exception occurred:\n")
            traceback.print_exc(file=log)
    finally:
        pythoncom.CoUninitialize()

def main():
    base_paths = [
        r"C:\Projects\Run1",
        r"C:\Projects\Run2"
    ]
    plans = [
        "T1_100yrs_30CC_V01",
        "T1_100yrs_30CC_03"
    ]
    project_file = "DCP2_AB.prj"

    processes = []
    for i, (folder, plan) in enumerate(zip(base_paths, plans), start=1):
        full_project_path = os.path.join(folder, project_file)
        log_file = os.path.join(folder, f"plan{i}_log.txt")

        p = multiprocessing.Process(target=run_hecras, args=(full_project_path, plan, log_file))
        processes.append(p)
        p.start()

    for p in processes:
        p.join()

    print("All simulations completed. Check log files in each run directory.")

if __name__ == "__main__":
    main()
