# -*- coding: utf-8 -*-
"""
Created on Mon Feb 16 09:18:40 2026

@author: Siamak.Farrokhzadeh
"""

import os
import time
import shutil
import tempfile
import sys
from multiprocessing import Process
import win32com.client
import pythoncom

def resource_path(relative_path):
    """Get absolute path to resource, works for dev and for PyInstaller"""
    try:
        # PyInstaller creates a temp folder and stores path in _MEIPASS
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")

    return os.path.join(base_path, relative_path)

def check_hecras_installed():
    """Check if HECRAS is installed and accessible"""
    try:
        pythoncom.CoInitialize()
        ras = win32com.client.Dispatch("RAS66.HECRASController")
        ras.QuitRas()
        pythoncom.CoUninitialize()
        return True
    except Exception as e:
        print(f"HECRAS check failed: {e}")
        return False

def run_hecras_plan(project_path, plan_name):
    try:
        pythoncom.CoInitialize()
        ras = win32com.client.Dispatch("RAS66.HECRASController")
        ras.ShowRas()
        
        print(f"[{plan_name}] Opening project: {project_path}")
        ras.Project_Open(project_path)
        time.sleep(5)
        
        print(f"[{plan_name}] Setting plan: {plan_name}")
        ras.Plan_SetCurrent(plan_name)
        
        print(f"[{plan_name}] Running simulation...")
        ras.Compute_CurrentPlan()
        
        while ras.Compute_Complete() == 0:
            print(f"[{plan_name}] Waiting for completion...")
            time.sleep(5)
        
        print(f"[{plan_name}] Simulation completed successfully!")
        ras.Project_Close()
        ras.QuitRas()
        
    except Exception as e:
        print(f"[{plan_name}] Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        pythoncom.CoUninitialize()

def update_dss_path_in_u_files(temp_dir, original_dss_path):
    if not original_dss_path:
        return
    
    normalized_path = os.path.normpath(original_dss_path)
    
    for file in os.listdir(temp_dir):
        if file.lower().endswith((".u01", ".u02", ".u03", ".u04")):
            u_file_path = os.path.join(temp_dir, file)
            
            try:
                with open(u_file_path, 'r') as f:
                    lines = f.readlines()
                
                new_lines = []
                found = False
                for line in lines:
                    if "DSS File=" in line:
                        found = True
                        new_lines.append(f"DSS File={normalized_path}\n")
                        print(f"Updated DSS path in {file}")
                    else:
                        new_lines.append(line)
                
                if not found:
                    new_lines.insert(0, f"DSS File={normalized_path}\n")
                    print(f"Added DSS path to {file}")
                
                with open(u_file_path, 'w') as f:
                    f.writelines(new_lines)
            except Exception as e:
                print(f"Error updating {file}: {e}")

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
                try:
                    shutil.copy2(src, dst)
                    print(f"Copied: {file}")
                except Exception as e:
                    print(f"Error copying {file}: {e}")
        
        if file.endswith(f".p{suffix}.hdf"):
            src = os.path.join(temp_dir, file)
            dst = os.path.join(main_project_dir, file)
            try:
                shutil.copy2(src, dst)
                print(f"Copied HDF: {file}")
            except Exception as e:
                print(f"Error copying HDF {file}: {e}")

def cleanup_temp_dirs(temp_paths):
    """Clean up temporary directories"""
    for temp_project, _ in temp_paths:
        temp_dir = os.path.dirname(temp_project)
        try:
            shutil.rmtree(temp_dir)
            print(f"Cleaned up: {temp_dir}")
        except Exception as e:
            print(f"Error cleaning up {temp_dir}: {e}")

def run_simulations():
    # Configuration
    original_project_path = r"C:\Test\PRtest1.prj"
    main_project_dir = os.path.dirname(original_project_path)
    
    original_dss_path1 = r"C:\Test\100yCC_2024.dss"
    
    suffix1 = "03"
    suffix2 = "04"
    
    plans = [
        ("plan03", original_dss_path1, suffix1),
        ("plan04", original_dss_path1, suffix2),
    ]
    
    # Check HECRAS installation
    if not check_hecras_installed():
        print("ERROR: HECRAS is not properly installed or registered.")
        print("Please install HECRAS and ensure it's registered correctly.")
        input("Press Enter to exit...")
        return
    
    processes = []
    temp_paths = []
    
    try:
        # Create temp copies and start processes
        for plan_name, dss_path, suffix in plans:
            print(f"\nPreparing {plan_name}...")
            temp_project = copy_project_to_temp(original_project_path, dss_path)
            temp_paths.append((temp_project, suffix))
            
            p = Process(target=run_hecras_plan, args=(temp_project, plan_name))
            p.start()
            processes.append(p)
            print(f"Started {plan_name} in parallel")
        
        # Wait for all to complete
        for p in processes:
            p.join()
        
        print("\nAll simulations completed.")
        
        # Copy all results back
        for temp_project, suffix in temp_paths:
            copy_results_to_main_project(temp_project, main_project_dir, suffix)
        
        print("\nAll results copied to main project folder.")
        print("Open RAS Mapper and refresh to see new results.")
        
    except Exception as e:
        print(f"Error during simulation: {e}")
        import traceback
        traceback.print_exc()
    finally:
        # Cleanup
        print("\nCleaning up temporary files...")
        cleanup_temp_dirs(temp_paths)
        
    input("\nPress Enter to exit...")

if __name__ == "__main__":
    run_simulations()