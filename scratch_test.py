import traceback
from dynamic_scheduling_master.src.dynamic_scheduling.supply_scheduling import run_supply_scheduling

try:
    print(run_supply_scheduling())
except Exception as e:
    traceback.print_exc()
