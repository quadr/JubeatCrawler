var app = angular.module("MusicInfoAdmin", [])

app.controller("MusicList", function($scope, $http) {
	$scope.disableUpload = true;
	$scope.loadList = function() {
		$http.get("../api/admin/music_list").
		success(function(data, status, headers, config) {
			$scope.music_list = data.music_info;
		}).                                                                                       
		error(function(data, status, headers, config) {                                           
		});
	};

	$scope.update = function(key, music) {
		var r = confirm(angular.toJson(music));
		if(r == true) {
			$http.post("../api/admin/music_list/update", { key: key, info: angular.copy(music) }).
			success(function(data, status, headers, config) {
				if(data.code != 'ok') {
					alert("error\n" + angular.toJson(data))
				}
				else {
					alert("updated!");
				}
				$scope.loadList();
			}).                                                                                       
			error(function(data, status, headers, config) {                                           
				$scope.loadList();
			});
		}
	};

	$scope.upload = function() {
		var input = $("#rawdata").get(0).files;
		var reader = new FileReader();
		reader.onload = function() {
			var dataURL = reader.result;
			var parts = dataURL.split(/[;,]/);
			if(parts.length == 3 && parts[0] == "data:text/plain" && parts[1] == "data")
			{
				$http.post("../api/admin/music_list", { data: parts[2] }).
				success(function(data, status, headers, confing) {
					if(data.code != 'ok') {
						alert("error\n" + angular.toJson(data))
					}
					else {
						alert("updated!");
					}
					$scope.loadList();
				}).
				error(function(data,status, headers, config) {
				});
			}
			else
			{
				alert("invalid file!");
			}
		};
		reader.readAsDataURL(input[0]);
	};

	$scope.fileSelected = function() {
		$scope.disableUpload = (this.value == '');
	}

	$scope.loadList();
});

$("#rawdata").fileinput({showUpload:false});
