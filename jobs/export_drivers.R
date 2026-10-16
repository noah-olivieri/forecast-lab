# Export the parts of nfl-drivers' results.rds that the weekly snapshot archives.
#   Rscript jobs/export_drivers.R RESULTS_RDS OUT_DIR
# Writes upcoming.csv (full_qb_ridge rows), features.csv (only if results has
# upcoming_features) and meta.json. Base R + jsonlite only; NA is written as empty / null.
args <- commandArgs(trailingOnly = TRUE)
if (length(args) != 2) stop("usage: export_drivers.R RESULTS_RDS OUT_DIR")
r <- readRDS(args[[1]])
need <- c("upcoming", "upcoming_dropped", "schedule_downloaded", "created")
missing <- setdiff(need, names(r))
if (length(missing)) stop("results.rds lacks: ", paste(missing, collapse = ", "))

out <- args[[2]]
dir.create(out, showWarnings = FALSE, recursive = TRUE)
iso <- function(x) {
  if (length(x) != 1 || is.na(x)) return(NA)
  format(as.POSIXct(x), "%Y-%m-%dT%H:%M:%SZ", tz = "UTC")
}
up <- as.data.frame(r$upcoming)
up <- up[up$model == "full_qb_ridge", , drop = FALSE]
up$gameday <- as.character(up$gameday)
utils::write.csv(up, file.path(out, "upcoming.csv"), row.names = FALSE, na = "")
if (!is.null(r$upcoming_features)) {
  utils::write.csv(as.data.frame(r$upcoming_features), file.path(out, "features.csv"),
                   row.names = FALSE, na = "")
}
meta <- list(created = iso(r$created), schedule_downloaded = iso(r$schedule_downloaded),
             upcoming_dropped = if (is.null(r$upcoming_dropped)) NA else as.integer(r$upcoming_dropped),
             n_rows = nrow(up),
             # absent in results.rds written before nfl-drivers recorded them -> null
             code_sha = if (is.null(r$code_sha)) NA else r$code_sha,
             code_dirty = if (is.null(r$code_dirty)) NA else r$code_dirty)
writeLines(jsonlite::toJSON(meta, auto_unbox = TRUE, na = "null"), file.path(out, "meta.json"))
