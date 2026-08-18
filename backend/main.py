#from src.research_lab.runners.strategy_runner import run
#from src.tests.test_db import run
#from src.tests.repository_smoke_test import test_repository_run
# from src.tests.test_domain_integration import test_domain_integration_run
# #from src.create_schema import create_schema
# from src.bootstrap.seed_database import SeedDatabase
# from src.persistence.database import Database 
# from src.persistence.database_session import DatabaseSession
# from src.tests.test_client_service import test_client_service_run
# from src.tests.test_portfolio_service import test_portfolio_service_run
# from src.tests.test_repository_smoke import test_repository_run
# from src.tests.test_investment_account_service import test_investment_account_service
# from src.tests.test_trade_service import test_record_buy_creates_new_holding_and_trade
# from src.tests.test_trade_service import test_record_sell_updates_holding_and_creates_trade
# #from src.research_lab.screeners.minervini_dyn_regime_backtester2 import minervini_dyn_regime_run
from install_library import install_library


def main():

    #create_schema()
    #test_repository_run()
    #test_client_service_run()
    #test_portfolio_service_run()
    #test_investment_account_service()
    #seed()
    #test_domain_integration_run()
    #test_record_buy_creates_new_holding_and_trade()
    #test_record_sell_updates_holding_and_creates_trade()
    #minervini_dyn_regime_run()
    install_library()

if __name__ == "__main__":

    main()