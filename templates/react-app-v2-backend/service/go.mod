module github.com/KazuhaHub/StockAnalysisPrediction-Report-Portal-Apps/apps/APP_ID/service

go 1.26.11

require (
	github.com/KazuhaHub/StockAnalysisPrediction-Report-Portal-Apps/packages/extensionprotocol v0.0.0
	github.com/KazuhaHub/StockAnalysisPrediction-Report-Portal-Apps/packages/proxy v0.0.0
)

replace github.com/KazuhaHub/StockAnalysisPrediction-Report-Portal-Apps/packages/extensionprotocol => ../../../packages/extensionprotocol
replace github.com/KazuhaHub/StockAnalysisPrediction-Report-Portal-Apps/packages/proxy => ../../../packages/proxy
