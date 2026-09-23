@echo off
rem US stock (S and P 500) bottom/surge scoring -> picks-log -> rescore at tradable prices.
rem Intended to run after the US close. Partial bars are dropped automatically.
rem ASCII only: cmd.exe reads .bat in the system codepage, UTF-8 comments break parsing.
cd /d %~dp0
if not exist logs mkdir logs
echo ==== %DATE% %TIME% start ==== >> logs\us_stock_score.log
python scripts\us-stock-score.py >> logs\us_stock_score.log 2>&1
python scripts\us-rescore-picks.py >> logs\us_stock_score.log 2>&1
echo ==== %DATE% %TIME% end ==== >> logs\us_stock_score.log
