var app = angular.module("MusicInfoAdmin", [])

app.controller("MusicList", function($scope, $http) {
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
	}

	$scope.loadList();
});
