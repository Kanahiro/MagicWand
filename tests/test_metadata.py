import configparser
import os


def test_metadata():
    """Test that metadata.txt will validate on plugins.qgis.org."""

    # You should update this list according to the latest in
    # https://github.com/qgis/qgis-django/blob/master/qgis-app/
    #        plugins/validator.py

    required_metadata = [
        "name",
        "description",
        "version",
        "qgisMinimumVersion",
        "email",
        "author",
    ]

    file_path = os.path.abspath(
        os.path.join(os.path.dirname(os.path.dirname(__file__)), "metadata.txt")
    )
    parser = configparser.ConfigParser()
    parser.optionxform = str
    parser.read(file_path)
    assert parser.has_section("general"), (
        f'Cannot find a section named "general" in {file_path}'
    )
    metadata = dict(parser.items("general"))
    for expectation in required_metadata:
        assert expectation in metadata, (
            f'Cannot find metadata "{expectation}" in metadata source ({file_path}).'
        )

    assert metadata["supportsQt6"] == "True"
