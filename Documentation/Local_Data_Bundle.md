# Local data bundle

The public GitHub repository ships source code, notebooks, screenshots, and reviewed project metadata. To run the complete application and notebook series, obtain the local BDA data bundle from the project owner and overlay the directories below onto the checkout. There is currently no public download for the bundle. The project records unresolved redistribution terms for several inputs. See the [data source review](Data_Source_Review.md).

| Local paths | Used by |
| --- | --- |
| `Processed_Data/daily_v1/serving.json`, `release.json`, `batch.json`, and the release, SQLite batch, and auxiliary files referenced by those pointers | Daily forecasts, Markets, Strategies, warehouse context, and operational notebooks |
| The archive and recent-source directories referenced in the active release manifest, including their observation and series Parquet files | Market history, notebook exercises, and publication checks |
| `Processed_Data/routing/` and `Processed_Data/intelligence_v1/`, including saved route and warehouse artifacts and future-price evidence | Maps, strategies, logistics notebooks, and forecast evidence |
| `Dataset/`, `Dataset_Candidates/`, and the accepted raw partitions referenced by the refresh manifest | Raw notebook examples, source-refresh provenance, and historical verification |
| Historical `Processed_Data/` artifacts, including validation predictions and saved evaluation outputs | Historical pages, the notebook research walkthrough, and the full integrity suite |

Copy the bundle with its repository-relative paths intact. Keep API credentials and machine-specific scheduler receipts local. A configured data.gov.in key is needed for new source downloads. Existing publications can be read without that credential.

The active serving pointer selects the files for one consistent publication. Forecasts expire at the IST date boundary. If the installed snapshot is older than today, use the README’s offline publication command with the complete local bundle.
