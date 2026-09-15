"""実バス試験は接続ポートを明示した場合だけ実行する。"""
def pytest_addoption(parser):
    parser.addoption("--can-port", help="実CAN試験用PicoアプリCDC")
