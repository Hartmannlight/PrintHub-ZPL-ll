# Raster print-service simulator

This is a test double for future image-only printer services. It implements
Print Service Protocol v2, accepts only the neutral PrintHub raster MIME type,
and writes one PNG per copy and page below `/data/output/<job-id>/`.

It is intentionally not a Niimbot driver and never claims real hardware
confirmation. Job responses contain `"simulation": true`.

Set `RASTER_TEST_TOKEN` to an individual value of at least 24 characters before
starting the service. Optional profile variables are `RASTER_TEST_DPI`,
`RASTER_TEST_WIDTH_PX`, and `RASTER_TEST_HEIGHT_PX`.
