module github.com/KazuhaHub/StockAnalysisPrediction-Report-Portal-Apps/apps/market-monitor/service

go 1.26.11

require (
	github.com/KazuhaHub/StockAnalysisPrediction-Report-Portal-Apps/packages/extensionprotocol v0.0.0
	github.com/KazuhaHub/StockAnalysisPrediction-Report-Portal-Apps/packages/proxy v0.0.0
	github.com/parquet-go/parquet-go v0.32.1
)

require (
	github.com/andybalholm/brotli v1.3.0 // indirect
	github.com/google/uuid v1.6.0 // indirect
	github.com/klauspost/compress v1.20.4 // indirect
	github.com/parquet-go/bitpack v1.0.3 // indirect
	github.com/parquet-go/jsonlite v1.5.5 // indirect
	github.com/pierrec/lz4/v4 v4.1.33 // indirect
	github.com/twpayne/go-geom v1.6.1 // indirect
	golang.org/x/sys v0.48.0 // indirect
	google.golang.org/protobuf v1.36.12 // indirect
)

replace github.com/KazuhaHub/StockAnalysisPrediction-Report-Portal-Apps/packages/extensionprotocol => ../../../packages/extensionprotocol

replace github.com/KazuhaHub/StockAnalysisPrediction-Report-Portal-Apps/packages/proxy => ../../../packages/proxy
