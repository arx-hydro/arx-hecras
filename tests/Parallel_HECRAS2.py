# -*- coding: utf-8 -*-
"""
Created on Mon Jun  2 09:25:24 2025

@author: Siamak.Farrokhzadeh
"""

import os
import time
import shutil
import tempfile
from multiprocessing import Process
import win32com.client
import pythoncom

def run_hecras_plan(project_path, plan_name):
    try:
        pythoncom.CoInitialize()

        ras = win32com.client.Dispatch("RAS66.HECRASController")
        ras.ShowRas()

        print(f"Opening project: {project_path}")
        ras.Project_Open(project_path)
        time.sleep(5)

        print(f"Setting plan: {plan_name}")
        ras.Plan_SetCurrent(plan_name)

        print(f"Running simulation: {plan_name}")
        ras.Compute_CurrentPlan()

        while ras.Compute_Complete() == 0:
          print(f"Waiting for plan: {plan_name} to complete...")
          time.sleep(5)

        print(f"Simulation completed for plan: {plan_name}")
        ras.Project_Close()

    except Exception as e:
        print(f"Error running plan '{plan_name}': {e}")
        import traceback
        traceback.print_exc()
        
def update_dss_path_in_u_files(temp_dir, original_dss_path):
    if not original_dss_path:
        return

    normalized_path = os.path.normpath(original_dss_path)

    for file in os.listdir(temp_dir):
        if file.lower().endswith((".u03", ".u04")):
            u_file_path = os.path.join(temp_dir, file)

            with open(u_file_path, 'r') as f:
                lines = f.readlines()

            new_lines = []
            found = False
            for line in lines:
                if "DSS File=" in line:
                    found = True
                    new_lines.append(f"DSS File={normalized_path}\n")
                    print(f"Updated DSS path in {file} to:\n   {normalized_path}")
                else:
                    new_lines.append(line)

            if not found:
                print(f"No DSS File= line found in {file}, adding one.")
                new_lines.insert(0, f"DSS File={normalized_path}\n")

            with open(u_file_path, 'w') as f:
                f.writelines(new_lines)

def copy_project_to_temp(original_project_path, original_dss_path):
    original_folder = os.path.dirname(original_project_path)
    temp_dir = tempfile.mkdtemp(prefix="HECRAS_")
    print(f"Copying project to temporary folder: {temp_dir}")

    # Copy all files from original project folder
    for item in os.listdir(original_folder):
        s = os.path.join(original_folder, item)
        d = os.path.join(temp_dir, item)
        if os.path.isdir(s):
            shutil.copytree(s, d, dirs_exist_ok=True)
        else:
            shutil.copy2(s, d)
            
     # Second: only after copying all files, update the DSS path (if any)
    if original_dss_path:
        update_dss_path_in_u_files(temp_dir, original_dss_path)

    temp_project_path = os.path.join(temp_dir, os.path.basename(original_project_path))
    return temp_project_path

def copy_results_to_main_project(temp_project_path, main_project_dir, suffix):
    important_exts = ['p', 'u', 'x', 'g', 'c', 'b', 'bco', 'dss', 'ic.o']
    temp_dir = os.path.dirname(temp_project_path)
    
    for file in os.listdir(temp_dir):
        for ext in important_exts:
            expected_suffix = f".{ext}{suffix}"
            if file.lower().endswith(expected_suffix.lower()):
                src = os.path.join(temp_dir, file)
                dst = os.path.join(main_project_dir, file)
                shutil.copy2(src, dst)
                print(f"Copying {file} → {main_project_dir}")
        
        if file.endswith(f".p{suffix}.hdf"):
            src = os.path.join(temp_dir, file)
            dst = os.path.join(main_project_dir, file)
            shutil.copy2(src, dst)
            print(f"Copying {file} → {main_project_dir}")        
            
def run_simulations():
    # Original project path and plan names
    original_project_path = r"C:\Test\PRtest1.prj"
    main_project_dir = os.path.dirname(original_project_path)
    
    original_dss_path1 = r"C:\Test\100yCC_2024.dss"
    
    suffix1 = "03"
    suffix2 = "04"
    
    plans = [
        ("plan03", original_dss_path1, suffix1),
        ("plan04", original_dss_path1, suffix2),
        # Add more here if needed
    ]

    processes = []
    temp_paths = []
    
    for plan_name, dss_path, suffix in plans:
       temp_project = copy_project_to_temp(original_project_path, dss_path)
       temp_paths.append((temp_project, suffix))

       p = Process(target=run_hecras_plan, args=(temp_project, plan_name))
       p.start()
       processes.append(p)

     # Wait for all to complete
    for p in processes:
        p.join()

    print("All simulations completed.")

    # Copy all results back
    for temp_project, suffix in temp_paths:
        copy_results_to_main_project(temp_project, main_project_dir, suffix)

    print("All results copied. Open RAS Mapper and refresh.")

if __name__ == "__main__":
    run_simulations()