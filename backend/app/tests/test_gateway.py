from ib_insync import IB, Stock


def test_connection():
    ib = IB()
    try:
        print("Connecting to IB Gateway on 127.0.0.1:4001...")
        ib.connect("127.0.0.1", 4001, clientId=99, timeout=10)
        print(" Connected successfully to IB Gateway!")

        # 1. Qualify a US contract
        contract = Stock("AAPL", "SMART", "USD")
        ib.qualifyContracts(contract)
        print(f" Contract qualified: {contract.symbol} (ConId: {contract.conId})")

        # 2. Check balance / account
        vals = [
            v
            for v in ib.accountValues()
            if v.tag in ("TotalCashBalance", "AvailableFunds")
        ]
        if vals:
            print(
                f" Account summary: {vals[0].tag} = {vals[0].value} {vals[0].currency}"
            )

    except Exception as e:
        print(f"❌ Connection failed: {e}")
    finally:
        if ib.isConnected():
            ib.disconnect()
            print("🔌 Disconnected cleanly.")


if __name__ == "__main__":
    test_connection()
