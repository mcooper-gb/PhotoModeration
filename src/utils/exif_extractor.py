"""EXIF data extraction utilities."""
from PIL import Image
from PIL.ExifTags import TAGS, GPSTAGS
from datetime import datetime


class ExifExtractor:
    """Extract and process EXIF metadata from images."""

    @staticmethod
    def extract_metadata(image_path):
        """
        Extract EXIF metadata from an image.

        Args:
            image_path: Path to the image file

        Returns:
            dict: Extracted metadata including date_taken, location, and google_maps_link
                  Returns None if no EXIF data is available
        """
        try:
            image = Image.open(image_path)
            exif_data = image.getexif()

            if not exif_data:
                return None

            metadata = {}

            for tag_id, value in exif_data.items():
                tag = TAGS.get(tag_id, tag_id)

                if tag == 'DateTimeOriginal' or tag == 'DateTime':
                    try:
                        metadata['date_taken'] = datetime.strptime(
                            str(value), '%Y:%m:%d %H:%M:%S'
                        ).strftime('%Y-%m-%d %H:%M:%S')
                    except:
                        metadata['date_taken'] = str(value)

                elif tag == 'GPSInfo':
                    gps_data = {}
                    for gps_tag_id in value:
                        gps_tag = GPSTAGS.get(gps_tag_id, gps_tag_id)
                        gps_data[gps_tag] = value[gps_tag_id]

                    lat = ExifExtractor._convert_gps_to_decimal(
                        gps_data.get('GPSLatitude'),
                        gps_data.get('GPSLatitudeRef')
                    )
                    lon = ExifExtractor._convert_gps_to_decimal(
                        gps_data.get('GPSLongitude'),
                        gps_data.get('GPSLongitudeRef')
                    )

                    if lat and lon:
                        metadata['location'] = f"{lat}, {lon}"
                        metadata['google_maps_link'] = f"https://www.google.com/maps?q={lat},{lon}"

            return metadata if metadata else None

        except Exception as e:
            print(f"Error extracting EXIF data from {image_path}: {e}")
            return None

    @staticmethod
    def _convert_gps_to_decimal(gps_coords, gps_ref):
        """
        Convert GPS coordinates to decimal format.

        Args:
            gps_coords: Tuple of (degrees, minutes, seconds)
            gps_ref: Reference direction ('N', 'S', 'E', 'W')

        Returns:
            float: Decimal coordinate or None if conversion fails
        """
        if not gps_coords or not gps_ref:
            return None

        try:
            degrees = float(gps_coords[0])
            minutes = float(gps_coords[1])
            seconds = float(gps_coords[2])

            decimal = degrees + (minutes / 60.0) + (seconds / 3600.0)

            if gps_ref in ['S', 'W']:
                decimal = -decimal

            return decimal
        except:
            return None
